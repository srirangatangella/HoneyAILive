from __future__ import annotations

import asyncio
import logging
import re
from contextlib import suppress
from typing import Any
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect

from agents.planner_agent import PlannerAgent
from agents.reasoning_agent import DIY_SYSTEM_PROMPT, GENERAL_SYSTEM_PROMPT, ReasoningAgent
from app.models import ChatTurn, ClientEnvelope, ServerEnvelope, SessionState
from memory.memory_manager import MemoryManager

logger = logging.getLogger(__name__)

META_HEADING_RE = re.compile(r"\*\*[^*]*(analyzing|interpreting|clarifying|identifying|defining)[^*]*\*\*", re.IGNORECASE)
FIRST_PERSON_META_RE = re.compile(
    r"\b(i|i'm|iâ€™ve|i've|i am|my)\b.*\b(analysis|focus|noticed|observed|examined|identified|interpretation|formulated|synthesized|pinpointed|noted|working|ready|approach|response)\b",
    re.IGNORECASE,
)
FORBIDDEN_META_RE = re.compile(
    r"\b(analysis|interpreting|analyzing|clarifying|identifying|working hypothesis|user's query|my interpretation|i formulated|i synthesized)\b",
    re.IGNORECASE,
)


def _normalize_sentence(sentence: str) -> str:
    cleaned = sentence.strip(" -:\n\t")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def sanitize_assistant_text(text: str) -> str:
    cleaned = META_HEADING_RE.sub(" ", text).replace("**", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""

    raw_sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    kept_sentences: list[str] = []

    for sentence in raw_sentences:
        current = _normalize_sentence(sentence)
        if not current:
            continue

        lower = current.lower()
        if FIRST_PERSON_META_RE.search(current):
            continue
        if FORBIDDEN_META_RE.search(current) and lower.startswith(("i ", "i'", "my ")):
            continue

        current = re.sub(r"(?i)^the image clearly presents\s+", "I can see ", current)
        current = re.sub(r"(?i)^the image shows\s+", "I can see ", current)
        current = re.sub(r"(?i)^this combination strongly suggests\s+", "It looks like ", current)
        current = re.sub(r"(?i)^the bottle is\s+", "It is a bottle that is ", current)
        current = re.sub(r"(?i)^it'?s\s+", "It is ", current)
        current = re.sub(r"(?i)^the product as\s+", "It looks like ", current)
        current = re.sub(r"(?i)^now,?\s*", "", current)
        current = re.sub(r"(?i)^this suggests\s+", "It suggests ", current)
        current = _normalize_sentence(current)

        if not current:
            continue
        if FIRST_PERSON_META_RE.search(current):
            continue
        if FORBIDDEN_META_RE.search(current) and current.lower().startswith(("i ", "i'", "my ")):
            continue
        kept_sentences.append(current)

    result = " ".join(kept_sentences).strip()
    result = re.sub(r"\s+", " ", result)
    return result


class HoneyWebSocketServer:
    def __init__(self, memory_manager: MemoryManager, gemini_factory, vision_analyzer=None, settings=None) -> None:
        self.memory_manager = memory_manager
        self.gemini_factory = gemini_factory
        self.vision_analyzer = vision_analyzer
        self.planner = PlannerAgent(settings=settings)
        self.reasoner = ReasoningAgent()
        self._session_state: dict[str, SessionState] = {}

    async def handle(self, websocket: WebSocket) -> None:
        await websocket.accept()
        session_id = str(uuid4())
        state = SessionState(session_id=session_id)
        self._session_state[session_id] = state
        session_ctx: dict[str, Any] = {
            "gemini_session": None,
            "receiver_task": None,
            "restart_lock": asyncio.Lock(),
            "session_token": 0,
        }
        await self._start_gemini_session(websocket, session_id, state, session_ctx)

        await websocket.send_json(
            ServerEnvelope(
                type="session_started",
                message="HoneyAI session started.",
                data={
                    "sessionId": session_id,
                    "runtime": type(session_ctx["gemini_session"]).__name__,
                    "assistantMode": state.assistant_mode,
                    "aiReadyForFrames": True,
                },
            ).model_dump()
        )

        try:
            while True:
                payload = await websocket.receive_json()
                envelope = ClientEnvelope.model_validate(payload)
                await self._handle_message(websocket, session_id, state, envelope, session_ctx)
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected for session %s", session_id)
        except Exception:
            logger.exception("Unhandled websocket error for session %s", session_id)
        finally:
            await self._stop_gemini_session(session_ctx)
            self._session_state.pop(session_id, None)

    # ── Session lifecycle (simplified — one long-lived session) ────────────

    async def _start_gemini_session(
        self,
        websocket: WebSocket,
        session_id: str,
        state: SessionState,
        session_ctx: dict[str, Any],
        resume_handle: str | None = None,
    ) -> None:
        gemini_session = await self.gemini_factory.create_session(
            state.assistant_mode, resume_handle=resume_handle
        )
        session_ctx["session_token"] = int(session_ctx.get("session_token", 0)) + 1
        session_token = session_ctx["session_token"]
        receiver_task = asyncio.create_task(
            self._forward_gemini_events(websocket, session_id, state, gemini_session, session_ctx, session_token)
        )
        session_ctx["gemini_session"] = gemini_session
        session_ctx["receiver_task"] = receiver_task

    async def _stop_gemini_session(self, session_ctx: dict[str, Any]) -> None:
        receiver_task = session_ctx.get("receiver_task")
        session_ctx["receiver_task"] = None
        if receiver_task:
            receiver_task.cancel()
            with suppress(asyncio.CancelledError, TimeoutError, Exception):
                await asyncio.wait_for(receiver_task, timeout=1.0)

        gemini_session = session_ctx.get("gemini_session")
        session_ctx["gemini_session"] = None
        if gemini_session:
            with suppress(Exception, TimeoutError):
                await asyncio.wait_for(gemini_session.close(), timeout=2.0)

    async def _reconnect_gemini_session(
        self,
        websocket: WebSocket,
        session_id: str,
        state: SessionState,
        session_ctx: dict[str, Any],
        reason: str,
    ) -> bool:
        """Reconnect using session resumption. Returns True on success."""
        async with session_ctx["restart_lock"]:
            # Grab resume handle before closing
            old_session = session_ctx.get("gemini_session")
            resume_handle = getattr(old_session, "resume_handle", None) if old_session else None

            await self._stop_gemini_session(session_ctx)

            try:
                await self._start_gemini_session(
                    websocket, session_id, state, session_ctx,
                    resume_handle=resume_handle,
                )
                logger.info("Gemini session reconnected for %s (reason: %s)", session_id, reason)
                with suppress(Exception):
                    await websocket.send_json(
                        ServerEnvelope(
                            type="session_recovered",
                            message="Gemini Live reconnected.",
                            data={
                                "runtime": type(session_ctx["gemini_session"]).__name__,
                                "assistantMode": state.assistant_mode,
                                "aiReadyForFrames": True,
                            },
                        ).model_dump()
                    )
                return True
            except Exception:
                logger.exception("Failed to reconnect Gemini session for %s", session_id)
                with suppress(Exception):
                    await websocket.send_json(
                        ServerEnvelope(
                            type="session_warning",
                            message="Gemini Live reconnect failed. Please restart the AI session.",
                            data={"aiReadyForFrames": False},
                        ).model_dump()
                    )
                return False

    # ── Message handling (simplified — no polling, no per-turn restart) ────

    async def _handle_message(
        self,
        websocket: WebSocket,
        session_id: str,
        state: SessionState,
        envelope: ClientEnvelope,
        session_ctx: dict[str, Any],
    ) -> None:
        if envelope.type == "mode_update":
            mode = envelope.meta.get("assistantMode")
            if mode in {"general", "diy"} and mode != state.assistant_mode:
                state.assistant_mode = mode
                if mode == "general":
                    state.current_plan = None
                # Reconnect with new system prompt for new mode
                await self._reconnect_gemini_session(
                    websocket, session_id, state, session_ctx, f"mode change to {mode}"
                )
                await websocket.send_json(ServerEnvelope(type="mode_changed", data={"assistantMode": mode}).model_dump())
            return

        if envelope.type == "text" and envelope.text:
            if envelope.meta.get("assistantMode") in {"general", "diy"}:
                new_mode = envelope.meta["assistantMode"]
                if new_mode != state.assistant_mode:
                    state.assistant_mode = new_mode
                    if new_mode == "general":
                        state.current_plan = None
                    await self._reconnect_gemini_session(
                        websocket, session_id, state, session_ctx, f"mode change to {new_mode}"
                    )

            await self._ingest_user_goal(websocket, session_id, state, envelope.text)
            state.last_seen_summary = None

            # Run vision analysis in parallel (if image attached)
            vision_task = None
            if envelope.image and self.vision_analyzer is not None:
                vision_task = asyncio.create_task(
                    self.vision_analyzer.analyze_image(
                        question=envelope.text,
                        image_b64=envelope.image,
                        mime_type=envelope.mime_type or "image/jpeg",
                        assistant_mode=state.assistant_mode,
                    )
                )

            if vision_task is not None:
                state.last_seen_summary = await vision_task

            # Build context and send — no polling, no restart, just send
            long_term_context = await self.memory_manager.get_long_term_memories(limit=10)
            context_prompt = self.reasoner.build_context_prompt(
                session_state=state,
                short_term_context=self.memory_manager.recent_context(session_id),
                long_term_context=long_term_context,
                latest_visual_summary=state.last_seen_summary,
            )
            gemini_session = session_ctx.get("gemini_session")
            if gemini_session is None:
                with suppress(Exception):
                    await websocket.send_json(
                        ServerEnvelope(
                            type="session_warning",
                            message="AI session is not active. Please restart.",
                            data={"aiReadyForFrames": False},
                        ).model_dump()
                    )
                return

            try:
                await gemini_session.send_text(
                    envelope.text,
                    context_prompt,
                    image=None,
                    mime_type=envelope.mime_type or "image/jpeg",
                )
            except Exception:
                logger.exception("Failed to send text to Gemini for session %s, attempting reconnect", session_id)
                reconnected = await self._reconnect_gemini_session(
                    websocket, session_id, state, session_ctx, "send_text failed"
                )
                if reconnected:
                    try:
                        await session_ctx["gemini_session"].send_text(
                            envelope.text,
                            context_prompt,
                            image=None,
                            mime_type=envelope.mime_type or "image/jpeg",
                        )
                    except Exception:
                        logger.exception("Retry send_text also failed for session %s", session_id)
                        with suppress(Exception):
                            await websocket.send_json(
                                ServerEnvelope(
                                    type="session_warning",
                                    message="The AI could not answer this turn. Please try again.",
                                    data={"aiReadyForFrames": False},
                                ).model_dump()
                            )
            return

        if envelope.type == "step_update":
            await self._apply_step_update(websocket, state, envelope)
            return

        if envelope.type == "ping":
            await websocket.send_json(ServerEnvelope(type="pong").model_dump())

    async def _ingest_user_goal(self, websocket: WebSocket, session_id: str, state: SessionState, user_text: str) -> None:
        state.current_goal = user_text
        state.last_user_text = user_text
        self.memory_manager.add_turn(session_id, ChatTurn(role="user", content=user_text))

        if state.assistant_mode == "diy":
            if state.current_plan is None:
                state.current_plan = await self.planner.create_plan_async(user_text, image_description=state.last_seen_summary)
            await websocket.send_json(ServerEnvelope(type="task_plan", data=state.current_plan.model_dump(mode="json")).model_dump())
        else:
            state.current_plan = None

    async def _apply_step_update(self, websocket: WebSocket, state: SessionState, envelope: ClientEnvelope) -> None:
        if state.assistant_mode != "diy" or not state.current_plan:
            return
        step_id = envelope.meta.get("stepId")
        status = envelope.meta.get("status")
        for index, step in enumerate(state.current_plan.steps):
            if step.id != step_id:
                continue
            step.status = status
            if status == "completed" and index + 1 < len(state.current_plan.steps):
                next_step = state.current_plan.steps[index + 1]
                if next_step.status == "pending":
                    next_step.status = "in_progress"
                    state.current_plan.current_step_id = next_step.id
            await websocket.send_json(ServerEnvelope(type="task_plan", data=state.current_plan.model_dump(mode="json")).model_dump())
            return

    # ── Gemini event forwarding (with auto-reconnect on drop) ─────────────

    async def _forward_gemini_events(
        self,
        websocket: WebSocket,
        session_id: str,
        state: SessionState,
        gemini_session,
        session_ctx: dict[str, Any],
        session_token: int,
    ) -> None:
        try:
            async for event in gemini_session.receive():
                if session_ctx.get("session_token") != session_token:
                    return

                # --- Interruption: clear audio on frontend ---
                if event.kind == "interrupted":
                    with suppress(Exception):
                        await websocket.send_json(
                            ServerEnvelope(
                                type="interrupted",
                                message="Response interrupted.",
                                data={"aiReadyForFrames": True},
                            ).model_dump()
                        )
                    continue

                # --- GoAway: proactive reconnect ---
                if event.kind == "go_away":
                    logger.info("GoAway event for session %s, scheduling reconnect", session_id)
                    # Don't reconnect here — let the receive loop end naturally,
                    # and the except/finally below will handle reconnection.
                    continue

                # --- Audio chunks ---
                if event.kind == "assistant_audio" and event.audio:
                    await websocket.send_json(
                        ServerEnvelope(
                            type="assistant_audio",
                            audio=event.audio,
                            mime_type=event.mime_type,
                            data={
                                "assistantMode": self._session_state[session_id].assistant_mode,
                                "aiReadyForFrames": True,
                            },
                        ).model_dump()
                    )
                    continue

                # --- Text / transcript ---
                if event.kind in {"assistant_text", "transcript"} and event.text:
                    if event.kind == "assistant_text":
                        cleaned_text = sanitize_assistant_text(event.text)
                        if not cleaned_text:
                            continue
                        self.memory_manager.add_turn(session_id, ChatTurn(role="assistant", content=cleaned_text))
                        user_input = self._session_state[session_id].last_user_text or "voice/audio input"
                        await self.memory_manager.persist_summary(user_input=user_input, ai_response=cleaned_text, tags=[self._session_state[session_id].assistant_mode])
                        await websocket.send_json(
                            ServerEnvelope(
                                type="assistant_text",
                                text=cleaned_text,
                                data={
                                    "assistantMode": self._session_state[session_id].assistant_mode,
                                    "systemPrompt": DIY_SYSTEM_PROMPT if self._session_state[session_id].assistant_mode == "diy" else GENERAL_SYSTEM_PROMPT,
                                    "aiReadyForFrames": True,
                                },
                            ).model_dump()
                        )
                        continue

                    self._session_state[session_id].last_user_text = event.text.strip()
                    await websocket.send_json(ServerEnvelope(type="transcript", text=event.text).model_dump())
                    continue

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Gemini receive loop failed for session %s", session_id)

        # --- Auto-reconnect on session drop (GoAway or unexpected close) ---
        if session_ctx.get("session_token") == session_token:
            logger.info("Gemini session ended for %s, attempting auto-reconnect with session resumption", session_id)
            with suppress(Exception):
                await websocket.send_json(
                    ServerEnvelope(
                        type="session_warning",
                        message="Live AI connection refreshing...",
                        data={"aiReadyForFrames": False},
                    ).model_dump()
                )
            await self._reconnect_gemini_session(
                websocket, session_id, state, session_ctx, "session ended / GoAway"
            )

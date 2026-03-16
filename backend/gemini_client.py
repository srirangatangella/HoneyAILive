from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal

from agents.reasoning_agent import DIY_SYSTEM_PROMPT, GENERAL_SYSTEM_PROMPT
from app.config import Settings

logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover
    genai = None
    types = None


@dataclass
class GeminiEvent:
    kind: str
    text: str | None = None
    audio: str | None = None
    mime_type: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class MockGeminiLiveSession:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[GeminiEvent] = asyncio.Queue()

    async def send_text(
        self,
        text: str,
        context_prompt: str,
        image_b64: str | None = None,
        mime_type: str = "image/jpeg",
    ) -> None:
        del context_prompt, mime_type
        guidance = (
            "I'm ready to help. Keep the important part of the device or screen in view, "
            "and we'll go through this together one step at a time."
        )
        visual_note = " I also received the latest visual context." if image_b64 else ""
        await self._queue.put(
            GeminiEvent(
                kind="assistant_text",
                text=f"{guidance}{visual_note}\n\nLet's start with this: {text}",
            )
        )

    async def send_audio(self, audio_b64: str, mime_type: str) -> None:
        del audio_b64, mime_type
        await self._queue.put(GeminiEvent(kind="transcript", text="Audio chunk received."))

    async def receive(self) -> AsyncIterator[GeminiEvent]:
        while True:
            event = await self._queue.get()
            yield event

    async def close(self) -> None:
        return None

    @property
    def resume_handle(self) -> str | None:
        return None


class GoogleGeminiLiveSession:
    """Long-lived Gemini Live session with session resumption and compression."""

    def __init__(self, settings: Settings, system_prompt: str) -> None:
        self.settings = settings
        self.system_prompt = system_prompt
        self.client = genai.Client(
            api_key=settings.google_api_key,
            http_options={"api_version": "v1alpha"},
        )
        self._session = None
        self._receiver_task: asyncio.Task | None = None
        self._queue: asyncio.Queue[GeminiEvent] = asyncio.Queue()
        self._manager = None
        self._resume_handle: str | None = None

    @property
    def resume_handle(self) -> str | None:
        return self._resume_handle

    def _build_config(self, resume_handle: str | None = None):
        thinking_budget = self.settings.gemini_thinking_budget
        # Proactivity and thinking are only supported on native-audio -12-2025+ models
        is_native_12 = "12-2025" in self.settings.gemini_model

        if types is None:
            config: dict[str, Any] = {
                "response_modalities": ["AUDIO"],
                "system_instruction": self.system_prompt,
                "input_audio_transcription": {},
                "output_audio_transcription": {},
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {
                            "voice_name": self.settings.gemini_voice_name,
                        }
                    }
                },
                "enable_affective_dialog": True,
                "context_window_compression": {
                    "sliding_window": {},
                },
                "session_resumption": {
                    "handle": resume_handle,
                },
            }
            if is_native_12:
                config["proactivity"] = {"proactive_audio": True}
            if is_native_12 and thinking_budget is not None:
                config["thinking_config"] = {"thinking_budget": thinking_budget}
            return config

        session_resumption = types.SessionResumptionConfig(
            handle=resume_handle,
        )

        config_obj = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=self.system_prompt,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.settings.gemini_voice_name,
                    )
                )
            ),
            enable_affective_dialog=True,
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(),
            ),
            session_resumption=session_resumption,
        )

        if is_native_12:
            config_obj.proactivity = types.ProactivityConfig(proactive_audio=True)

        if is_native_12 and thinking_budget is not None:
            config_obj.thinking_config = types.ThinkingConfig(
                thinking_budget=thinking_budget,
            )

        return config_obj

    async def connect(self, resume_handle: str | None = None) -> None:
        self._resume_handle = resume_handle
        config = self._build_config(resume_handle=resume_handle)
        self._manager = self.client.aio.live.connect(
            model=self.settings.gemini_model, config=config
        )
        self._session = await self._manager.__aenter__()
        self._receiver_task = asyncio.create_task(self._receive_loop())

    async def _receive_loop(self) -> None:
        assert self._session is not None
        pending_output_transcript: list[str] = []

        async for response in self._session.receive():
            server_content = getattr(response, "server_content", None)

            # --- Session resumption updates ---
            resumption_update = getattr(response, "session_resumption_update", None)
            if resumption_update:
                new_handle = getattr(resumption_update, "new_handle", None)
                if new_handle:
                    self._resume_handle = new_handle
                    logger.debug("Session resumption handle updated")

            # --- GoAway message (server is about to disconnect) ---
            go_away = getattr(response, "go_away", None)
            if go_away:
                time_left = getattr(go_away, "time_left", None)
                logger.warning("Gemini Live GoAway received, time_left=%s", time_left)
                await self._queue.put(GeminiEvent(kind="go_away", data={"time_left": str(time_left) if time_left else None}))

            if not server_content:
                continue

            # --- Interruption handling ---
            interrupted = getattr(server_content, "interrupted", False)
            if interrupted:
                pending_output_transcript = []
                await self._queue.put(GeminiEvent(kind="interrupted"))
                continue

            # --- Input transcription ---
            input_transcription = getattr(server_content, "input_transcription", None)
            if input_transcription and getattr(input_transcription, "text", None):
                await self._queue.put(GeminiEvent(kind="transcript", text=input_transcription.text))

            # --- Output transcription ---
            output_transcription = getattr(server_content, "output_transcription", None)
            if output_transcription and getattr(output_transcription, "text", None):
                pending_output_transcript.append(output_transcription.text)

            # --- Audio data ---
            model_turn = getattr(server_content, "model_turn", None)
            if model_turn and getattr(model_turn, "parts", None):
                for part in model_turn.parts:
                    inline_data = getattr(part, "inline_data", None)
                    if inline_data and getattr(inline_data, "data", None):
                        data = inline_data.data
                        audio_b64 = base64.b64encode(
                            data if isinstance(data, (bytes, bytearray)) else bytes(data)
                        ).decode("utf-8")
                        await self._queue.put(
                            GeminiEvent(
                                kind="assistant_audio",
                                audio=audio_b64,
                                mime_type=getattr(inline_data, "mime_type", "audio/pcm;rate=24000"),
                            )
                        )

            # --- Turn complete ---
            if getattr(server_content, "turn_complete", False):
                combined = " ".join(part.strip() for part in pending_output_transcript if part.strip()).strip()
                if combined:
                    await self._queue.put(GeminiEvent(kind="assistant_text", text=combined))
                pending_output_transcript = []

        # Flush any remaining transcript
        combined = " ".join(part.strip() for part in pending_output_transcript if part.strip()).strip()
        if combined:
            await self._queue.put(GeminiEvent(kind="assistant_text", text=combined))

    async def send_text(
        self,
        text: str,
        context_prompt: str,
        image_b64: str | None = None,
        mime_type: str = "image/jpeg",
    ) -> None:
        assert self._session is not None
        parts: list[dict[str, Any]] = [{"text": f"{context_prompt}\n\nUser request: {text}"}]
        if image_b64:
            image_bytes = base64.b64decode(image_b64)
            parts.append({"inline_data": {"mime_type": mime_type, "data": image_bytes}})
        turns = {"role": "user", "parts": parts}
        await self._session.send_client_content(turns=turns, turn_complete=True)

    async def send_audio(self, audio_b64: str, mime_type: str) -> None:
        assert self._session is not None
        audio_bytes = base64.b64decode(audio_b64)
        await self._session.send_realtime_input(audio=types.Blob(data=audio_bytes, mime_type=mime_type))

    async def receive(self) -> AsyncIterator[GeminiEvent]:
        while True:
            event = await self._queue.get()
            yield event

    async def close(self) -> None:
        receiver_task = self._receiver_task
        self._receiver_task = None
        if receiver_task:
            receiver_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError, Exception):
                await asyncio.wait_for(receiver_task, timeout=1.0)

        manager = self._manager
        self._manager = None
        self._session = None
        if manager is not None:
            with contextlib.suppress(TimeoutError, Exception):
                await asyncio.wait_for(manager.__aexit__(None, None, None), timeout=2.0)


class GeminiClientFactory:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _prompt_for_mode(self, assistant_mode: Literal["general", "diy"]) -> str:
        return DIY_SYSTEM_PROMPT if assistant_mode == "diy" else GENERAL_SYSTEM_PROMPT

    async def create_session(
        self,
        assistant_mode: Literal["general", "diy"] = "general",
        resume_handle: str | None = None,
    ) -> GoogleGeminiLiveSession | MockGeminiLiveSession:
        if self.settings.enable_gemini_live and self.settings.google_api_key and genai and types:
            session = GoogleGeminiLiveSession(self.settings, self._prompt_for_mode(assistant_mode))
            try:
                await session.connect(resume_handle=resume_handle)
                logger.info(
                    "Connected to Gemini Live model %s with voice %s in %s mode (resume=%s)",
                    self.settings.gemini_model,
                    self.settings.gemini_voice_name,
                    assistant_mode,
                    "yes" if resume_handle else "no",
                )
                return session
            except Exception:
                logger.exception("Gemini Live connection failed, falling back to mock mode")
        return MockGeminiLiveSession()

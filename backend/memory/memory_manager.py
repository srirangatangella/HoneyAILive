from __future__ import annotations

from app.models import ChatTurn, MemoryRecord
from memory.ltm import LongTermMemory
from memory.stm import ShortTermMemory


class MemoryManager:
    def __init__(self, ltm: LongTermMemory, stm_limit: int = 10) -> None:
        self.ltm = ltm
        self.stm_limit = stm_limit
        self._session_memories: dict[str, ShortTermMemory] = {}

    def for_session(self, session_id: str) -> ShortTermMemory:
        if session_id not in self._session_memories:
            self._session_memories[session_id] = ShortTermMemory(limit=self.stm_limit)
        return self._session_memories[session_id]

    def add_turn(self, session_id: str, turn: ChatTurn) -> None:
        self.for_session(session_id).add_turn(turn)

    def recent_context(self, session_id: str) -> str:
        return self.for_session(session_id).summarize()

    async def persist_summary(
        self,
        user_input: str,
        ai_response: str,
        tags: list[str] | None = None,
    ) -> None:
        await self.ltm.add_memory(
            MemoryRecord(
                user_input=user_input,
                ai_response=ai_response,
                tags=tags or [],
            )
        )
    async def get_long_term_memories(self, limit: int = 5) -> str:
        records = await self.ltm.recent_memories(limit=limit)
        if not records:
            return "No long-term memories found."
        return "\n".join(
            f"{rec.timestamp}: User: {rec.user_input} | AI: {rec.ai_response}"
            for rec in reversed(records)
        )

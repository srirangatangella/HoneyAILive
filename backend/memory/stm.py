from collections import deque

from app.models import ChatTurn


class ShortTermMemory:
    def __init__(self, limit: int = 10) -> None:
        self.limit = limit
        self._turns: deque[ChatTurn] = deque(maxlen=limit)

    def add_turn(self, turn: ChatTurn) -> None:
        self._turns.append(turn)

    def get_turns(self) -> list[ChatTurn]:
        return list(self._turns)

    def summarize(self) -> str:
        if not self._turns:
            return "No recent interactions."
        return "\n".join(f"{turn.role}: {turn.content}" for turn in self._turns)

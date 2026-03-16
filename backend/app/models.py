from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime = Field(default_factory=utc_now)
    meta: dict[str, Any] = Field(default_factory=dict)


class TaskStep(BaseModel):
    id: str
    title: str
    instruction: str
    status: Literal["pending", "in_progress", "completed", "blocked"] = "pending"
    validation_hint: str
    last_validation_reasoning: str | None = None


class TaskPlan(BaseModel):
    goal: str
    steps: list[TaskStep] = Field(default_factory=list)
    current_step_id: str | None = None


class SessionState(BaseModel):
    session_id: str
    assistant_mode: Literal["general", "diy"] = "general"
    current_goal: str | None = None
    current_plan: TaskPlan | None = None
    last_seen_summary: str | None = None
    last_user_text: str | None = None


class MemoryRecord(BaseModel):
    timestamp: datetime = Field(default_factory=utc_now)
    user_input: str
    ai_response: str
    tags: list[str] = Field(default_factory=list)


class ClientEnvelope(BaseModel):
    type: str
    text: str | None = None
    image: str | None = None
    audio: str | None = None
    mime_type: str | None = None
    session_id: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class ServerEnvelope(BaseModel):
    type: str
    message: str | None = None
    text: str | None = None
    audio: str | None = None
    mime_type: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

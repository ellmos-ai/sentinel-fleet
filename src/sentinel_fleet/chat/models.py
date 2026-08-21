"""Data model for chat sessions, messages and model races."""

import time
from enum import Enum
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator


class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatMode(str, Enum):
    """How an assistant turn was produced. Never guessed - set by the backend that ran."""
    GEMINI_LIVE = "gemini-live"
    DETERMINISTIC_DEMO = "deterministic-demo"
    BLOCKED = "blocked-by-model-armor"


class ChatMessage(BaseModel):
    message_id: str
    role: ChatRole
    content: str
    timestamp: float = Field(default_factory=time.time)
    # Provenance of an assistant turn. A user turn leaves these at their defaults.
    model: str = ""
    mode: ChatMode = ChatMode.DETERMINISTIC_DEMO
    latency_s: float = 0.0
    # True when the number above is a stand-in produced by the demo backend rather than
    # a measured model round trip. The UI must label it as such.
    latency_simulated: bool = False
    skill_ids: List[str] = Field(default_factory=list)
    prompt_id: str = ""
    prompt_version: str = ""
    blocked_patterns: List[str] = Field(default_factory=list)


class RaceLane(BaseModel):
    """One model's run of a shared prompt, executed under its own agent identity."""
    model: str
    agent_id: str
    content: str = ""
    mode: ChatMode = ChatMode.DETERMINISTIC_DEMO
    latency_s: float = 0.0
    latency_simulated: bool = False
    error: str = ""


class RaceVerdict(BaseModel):
    """Rubric result. `evaluated` is False whenever no judge model actually scored the lanes."""
    judge_model: str
    mode: ChatMode = ChatMode.DETERMINISTIC_DEMO
    evaluated: bool = False
    dimensions: List[str] = Field(default_factory=list)
    rows: List[Dict[str, str]] = Field(default_factory=list)
    summary: str = ""


class RaceRecord(BaseModel):
    race_id: str
    prompt: str
    created_at: float = Field(default_factory=time.time)
    lanes: List[RaceLane] = Field(default_factory=list)
    verdict: Optional[RaceVerdict] = None


class ChatSession(BaseModel):
    session_id: str
    title: str
    # Private by default. Older records load under a deliberately unreachable legacy owner
    # instead of becoming visible to every new public-demo visitor.
    owner_id: str = "workspace:legacy-unassigned"
    visibility: Literal["private", "department", "organization"] = "private"
    department_id: Optional[str] = None
    shared_with: List[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    messages: List[ChatMessage] = Field(default_factory=list)
    races: List[RaceRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def _scope_is_coherent(self) -> "ChatSession":
        if self.visibility == "department" and not self.department_id:
            raise ValueError("department-visible chat needs a department_id")
        if self.visibility != "department":
            self.department_id = None
        return self

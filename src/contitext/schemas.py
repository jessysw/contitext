"""Stable application-layer request and response contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AccessRole(StrEnum):
    reader = "reader"
    writer = "writer"
    owner = "owner"


class EventKind(StrEnum):
    note = "note"
    decision = "decision"
    question = "question"
    checkpoint = "checkpoint"
    handoff = "handoff"


class RecordEventKind(StrEnum):
    note = "note"
    decision = "decision"
    question = "question"
    checkpoint = "checkpoint"


class BindProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)


class ProjectBinding(BaseModel):
    principal_id: UUID
    project_id: str
    scope_id: str
    session_id: str
    updated_at: datetime


class RecordContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    project_id: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    event_kind: RecordEventKind
    payload: dict[str, Any]
    idempotency_key: str = Field(min_length=1)


class StoreContextEventRequest(BaseModel):
    """Internal persistence contract; handoffs enter only via HandoffRequest."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    event_kind: EventKind
    payload: dict[str, Any]
    idempotency_key: str = Field(min_length=1)


class HandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    next_action: str = Field(min_length=1)
    completed: list[str] = Field(default_factory=list)
    current: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1)


class ContextEventResult(BaseModel):
    event_id: UUID
    project_id: str
    principal_id: UUID
    scope_id: str
    session_id: str
    agent_id: str
    source_kind: str
    source_id: str
    event_kind: EventKind
    payload: dict[str, Any]
    idempotency_key: str
    created_at: datetime


class ProjectOverview(BaseModel):
    project_id: str
    display_name: str
    status: str


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    project_id: str = Field(min_length=1, max_length=257, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)?$")
    display_name: str = Field(min_length=1, max_length=256)

    @field_validator("display_name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("display_name must not be blank")
        return value


class AccessibleProject(ProjectOverview):
    role: AccessRole


class ProjectListPage(BaseModel):
    projects: list[AccessibleProject]
    next_cursor: str | None


class ProjectContext(BaseModel):
    """Bounded hydration bundle in fixed startup order."""

    overview: ProjectOverview
    status: ContextEventResult | None
    unresolved_questions: list[ContextEventResult]
    recent_decisions: list[ContextEventResult]
    latest_handoff: ContextEventResult | None


class ContextSearchResult(BaseModel):
    event: ContextEventResult
    rank: float


class ContextSearchPage(BaseModel):
    query: str
    results: list[ContextSearchResult]
    total_count: int
    next_cursor: str | None


class ProjectionResult(BaseModel):
    project_id: str
    projected_event_ids: list[UUID]
    files_changed: list[str]
    last_event_created_at: datetime | None
    last_event_id: UUID | None

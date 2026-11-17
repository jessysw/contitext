"""SQLAlchemy models for the Contitext foundation schema."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Principal(Base):
    __tablename__ = "principals"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProjectACL(Base):
    __tablename__ = "project_acl"
    __table_args__ = (CheckConstraint("role IN ('reader', 'writer', 'owner')", name="ck_project_acl_role"),)

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    principal_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("principals.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)


class ScopeBinding(Base):
    __tablename__ = "scope_bindings"

    principal_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("principals.id", ondelete="CASCADE"), primary_key=True)
    scope_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ContextEvent(Base):
    __tablename__ = "context_events"
    __table_args__ = (
        CheckConstraint("event_kind IN ('note', 'decision', 'question', 'checkpoint', 'handoff')", name="ck_context_events_kind"),
        UniqueConstraint("project_id", "idempotency_key", name="uq_context_events_project_idempotency"),
        Index("ix_context_events_project_created_event", "project_id", "created_at", "event_id"),
        Index("ix_context_events_project_kind_created", "project_id", "event_kind", "created_at"),
        Index("ix_context_events_project_source", "project_id", "source_kind", "source_id"),
        Index("ix_context_events_payload_search", text("to_tsvector('simple', lower(coalesce(payload::text, '')))"), postgresql_using="gin"),
    )

    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    principal_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("principals.id", ondelete="RESTRICT"), nullable=False)
    scope_id: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    agent_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )


class ProjectionOffset(Base):
    __tablename__ = "projection_offsets"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    last_event_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("context_events.event_id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

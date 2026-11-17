"""foundation schema

Revision ID: 0001_foundation
Revises:
Create Date: 2026-11-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "principals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "project_acl",
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("principals.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.CheckConstraint("role IN ('reader', 'writer', 'owner')", name="ck_project_acl_role"),
    )
    op.create_table(
        "scope_bindings",
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("principals.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("scope_id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "context_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("principals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("scope_id", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("event_kind", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("clock_timestamp()")),
        sa.CheckConstraint(
            "event_kind IN ('note', 'decision', 'question', 'checkpoint', 'handoff')",
            name="ck_context_events_kind",
        ),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_context_events_project_idempotency"),
    )
    op.create_index(
        "ix_context_events_project_created_event",
        "context_events",
        ["project_id", "created_at", "event_id"],
    )
    op.create_index(
        "ix_context_events_project_kind_created",
        "context_events",
        ["project_id", "event_kind", "created_at"],
    )
    op.create_index(
        "ix_context_events_project_source",
        "context_events",
        ["project_id", "source_kind", "source_id"],
    )
    op.create_index(
        "ix_context_events_payload_search",
        "context_events",
        [sa.text("to_tsvector('simple', lower(coalesce(payload::text, '')))")],
        postgresql_using="gin",
    )
    op.create_table(
        "projection_offsets",
        sa.Column("project_id", sa.Text(), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("last_event_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("context_events.event_id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    op.drop_table("projection_offsets")
    op.drop_index("ix_context_events_payload_search", table_name="context_events")
    op.drop_index("ix_context_events_project_source", table_name="context_events")
    op.drop_index("ix_context_events_project_kind_created", table_name="context_events")
    op.drop_index("ix_context_events_project_created_event", table_name="context_events")
    op.drop_table("context_events")
    op.drop_table("scope_bindings")
    op.drop_table("project_acl")
    op.drop_table("principals")
    op.drop_table("projects")

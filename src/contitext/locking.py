"""Shared PostgreSQL project transaction locking.

All context-event writers and the Markdown projector serialize on the same
64-bit advisory key: PostgreSQL ``hashtextextended(project_id, 0)``. Writers
assign ``clock_timestamp()`` only after acquiring this transaction lock, so a
projector cannot advance beyond an uncommitted event that will later appear
with an older ordering timestamp.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


PROJECT_TRANSACTION_LOCK_SQL = text(
    "SELECT pg_advisory_xact_lock(hashtextextended(CAST(:project_id AS text), 0))"
)


def acquire_project_transaction_lock(session: Session, project_id: UUID) -> None:
    """Serialize a project's event insertion and projection transactions."""

    session.execute(PROJECT_TRANSACTION_LOCK_SQL, {"project_id": project_id})

"""Explicit membership setup for legacy single-workspace regression fixtures."""
from sqlalchemy import text


def seed_members(connection):
    connection.execute(text(
        "INSERT INTO workspace_members (workspace_id, principal_id, role) "
        "SELECT '00000000-0000-4000-8000-000000000001', id, 'member' FROM principals "
        "ON CONFLICT DO NOTHING"
    ))

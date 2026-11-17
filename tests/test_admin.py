from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import create_engine, text

from contitext.admin import SeedACL, SeedDocument, SeedPrincipal, SeedProject, seed_database


def test_seed_is_idempotent_and_updates_metadata(migrated_database_url: str) -> None:
    principal_id = UUID("33333333-3333-4333-8333-333333333333")
    first = SeedDocument(
        projects=[SeedProject(id="alpha", display_name="Alpha", status="active")],
        principals=[SeedPrincipal(id=principal_id, name="Operator")],
        acls=[SeedACL(project_id="alpha", principal_id=principal_id, role="writer")],
    )
    assert seed_database(migrated_database_url, first) == {
        "projects": 1, "principals": 1, "acls": 1
    }
    updated = SeedDocument(
        projects=[SeedProject(id="alpha", display_name="Alpha Updated", status="paused")],
        principals=[SeedPrincipal(id=principal_id, name="Operator Updated")],
        acls=[SeedACL(project_id="alpha", principal_id=principal_id, role="owner")],
    )
    seed_database(migrated_database_url, updated)
    engine = create_engine(migrated_database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT display_name, status FROM projects WHERE id='alpha'"
            )).one() == ("Alpha Updated", "paused")
            assert connection.execute(text(
                "SELECT name FROM principals WHERE id=:id"
            ), {"id": principal_id}).scalar_one() == "Operator Updated"
            assert connection.execute(text(
                "SELECT role FROM project_acl WHERE project_id='alpha' AND principal_id=:id"
            ), {"id": principal_id}).scalar_one() == "owner"
            assert connection.execute(text("SELECT count(*) FROM projects")).scalar_one() == 1
            assert connection.execute(text("SELECT count(*) FROM principals")).scalar_one() == 1
            assert connection.execute(text("SELECT count(*) FROM project_acl")).scalar_one() == 1
    finally:
        engine.dispose()


def test_seed_rejects_undeclared_references(migrated_database_url: str) -> None:
    principal_id = UUID("44444444-4444-4444-8444-444444444444")
    document = SeedDocument(
        projects=[],
        principals=[SeedPrincipal(id=principal_id, name="Operator")],
        acls=[SeedACL(project_id="missing", principal_id=principal_id, role="owner")],
    )
    with pytest.raises(ValueError, match="ACL project"):
        seed_database(migrated_database_url, document)

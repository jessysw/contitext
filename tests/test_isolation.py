from __future__ import annotations

from workspace_fixtures import seed_members


import json
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from contitext.auth import (
    AuthenticationError,
    ProjectNotFoundError,
    TokenStore,
    require_project_access,
)


def test_token_store_resolves_identity_and_never_retains_plaintext() -> None:
    principal_id = uuid4()
    secret = "local-test-bearer-value"
    store = TokenStore.from_json(
        json.dumps({secret: {"principal_id": str(principal_id), "name": "Alice"}})
    )

    assert store.resolve(secret).principal_id == principal_id
    assert secret not in repr(store)
    assert secret not in repr(vars(store))
    with pytest.raises(AuthenticationError, match="invalid bearer credential"):
        store.resolve("unknown")


def test_unknown_and_unauthorized_projects_are_indistinguishable(
    migrated_database_url: str,
) -> None:
    engine = create_engine(migrated_database_url)
    allowed = uuid4()
    denied = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO projects (slug, workspace_id, display_name, status) VALUES ('alpha', '00000000-0000-4000-8000-000000000001', 'Alpha', 'active')")
            )
            connection.execute(
                text("INSERT INTO principals (id, name) VALUES (:id, 'Allowed'), (:denied, 'Denied')"),
                {"id": allowed, "denied": denied},
            )
            seed_members(connection)
            connection.execute(
                text("INSERT INTO project_acl (project_id, principal_id, role) VALUES ((SELECT id FROM projects WHERE workspace_id='00000000-0000-4000-8000-000000000001' AND slug='alpha'), :id, 'reader')"),
                {"id": allowed},
            )

        from sqlalchemy.orm import Session

        with Session(engine) as session:
            assert require_project_access(session, allowed, "alpha", "reader") == "reader"
            failures = []
            for principal_id, project_id in ((denied, "alpha"), (denied, "missing")):
                with pytest.raises(ProjectNotFoundError) as caught:
                    require_project_access(session, principal_id, project_id, "reader")
                failures.append((type(caught.value), str(caught.value)))
            assert failures[0] == failures[1]
            with pytest.raises(ProjectNotFoundError, match="project not found"):
                require_project_access(session, allowed, "alpha", "writer")
    finally:
        engine.dispose()

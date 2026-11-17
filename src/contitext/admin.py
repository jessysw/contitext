"""Idempotent local administration for projects, principals, and ACLs."""

from __future__ import annotations

import argparse
import json
import os
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.dialects.postgresql import insert

from contitext.config import ConfigurationError, Settings
from contitext.db import create_database_engine, create_session_factory
from contitext.models import Principal, Project, ProjectACL


class SeedProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    display_name: str = Field(min_length=1)
    status: str = Field(min_length=1)


class SeedPrincipal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    name: str = Field(min_length=1)


class SeedACL(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=1)
    principal_id: UUID
    role: Literal["reader", "writer", "owner"]


class SeedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projects: list[SeedProject] = Field(default_factory=list)
    principals: list[SeedPrincipal] = Field(default_factory=list)
    acls: list[SeedACL] = Field(default_factory=list)


def seed_database(database_url: str, document: SeedDocument) -> dict[str, int]:
    project_ids = {item.id for item in document.projects}
    principal_ids = {item.id for item in document.principals}
    if len(project_ids) != len(document.projects):
        raise ValueError("seed contains duplicate project ids")
    if len(principal_ids) != len(document.principals):
        raise ValueError("seed contains duplicate principal ids")
    if any(item.project_id not in project_ids for item in document.acls):
        raise ValueError("every ACL project must appear in seed projects")
    if any(item.principal_id not in principal_ids for item in document.acls):
        raise ValueError("every ACL principal must appear in seed principals")

    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    try:
        with factory.begin() as session:
            for item in document.projects:
                session.execute(
                    insert(Project)
                    .values(id=item.id, display_name=item.display_name, status=item.status)
                    .on_conflict_do_update(
                        index_elements=[Project.id],
                        set_={"display_name": item.display_name, "status": item.status},
                    )
                )
            for item in document.principals:
                session.execute(
                    insert(Principal)
                    .values(id=item.id, name=item.name)
                    .on_conflict_do_update(
                        index_elements=[Principal.id], set_={"name": item.name}
                    )
                )
            for item in document.acls:
                session.execute(
                    insert(ProjectACL)
                    .values(
                        project_id=item.project_id,
                        principal_id=item.principal_id,
                        role=item.role,
                    )
                    .on_conflict_do_update(
                        index_elements=[ProjectACL.project_id, ProjectACL.principal_id],
                        set_={"role": item.role},
                    )
                )
    finally:
        engine.dispose()
    return {
        "projects": len(document.projects),
        "principals": len(document.principals),
        "acls": len(document.acls),
    }


def _load_seed() -> SeedDocument:
    raw = os.environ.get("CONTITEXT_SEED_JSON")
    if not raw:
        raise ValueError("CONTITEXT_SEED_JSON is required")
    return SeedDocument.model_validate_json(raw)


def main(argv: list[str] | None = None, *, prog: str = "contitext-admin") -> None:
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("command", choices=["seed"])
    args = parser.parse_args(argv)
    try:
        if args.command == "seed":
            settings = Settings.from_env()
            counts = seed_database(settings.database_url, _load_seed())
            print(json.dumps({"status": "ok", **counts}, sort_keys=True))
    except (ConfigurationError, ValueError, ValidationError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()

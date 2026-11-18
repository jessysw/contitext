"""Idempotent local administration for projects, principals, and ACLs."""

from __future__ import annotations

import argparse
import json
import os
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select, delete, text
from sqlalchemy.exc import SQLAlchemyError

from contitext.auth import AuthenticationError
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


def seed_database(database_url: str, document: SeedDocument, *, if_empty: bool = False) -> dict[str, int]:
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
            if if_empty:
                # Coordinate simultaneous initial starts, but never reapply bootstrap ACLs
                # to an established deployment after an operator has revoked access.
                session.execute(text("LOCK TABLE projects, principals IN SHARE ROW EXCLUSIVE MODE"))
                if session.execute(select(Project.id).limit(1)).first() or session.execute(select(Principal.id).limit(1)).first():
                    return {"projects": 0, "principals": 0, "acls": 0}
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
    parser.add_argument("--if-empty", action="store_true", help="Seed only a new deployment; preserve later administration.")
    args = parser.parse_args(argv)
    try:
        if args.command == "seed":
            settings = Settings.from_env(require_auth=False)
            counts = seed_database(settings.database_url, _load_seed(), if_empty=args.if_empty)
            print(json.dumps({"status": "ok", **counts}, sort_keys=True))
    except ValidationError:
        parser.error("invalid seed document; check projects, principals, and ACL references")
    except (ConfigurationError, ValueError) as exc:
        parser.error(str(exc))
    except SQLAlchemyError:
        parser.error("database operation failed; check connectivity, migrations, and identifiers")


def add_management_commands(commands) -> None:
    """Local operator commands. These are deliberately not exposed to MCP clients."""
    project = commands.add_parser("project", help="Manage projects using trusted database access.")
    actions = project.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="List projects.")
    show = actions.add_parser("show", help="Show project metadata and access grants.")
    show.add_argument("project_id")
    create = actions.add_parser("create", help="Create a project and its first owner atomically.")
    create.add_argument("project_id")
    create.add_argument("--name", required=True)
    create.add_argument("--owner", type=UUID, help="Optional operator override; defaults to the authenticated MCP identity.")
    update = actions.add_parser("update", help="Update project metadata without deleting history.")
    update.add_argument("project_id")
    update.add_argument("--name")
    update.add_argument("--status")
    principal = commands.add_parser("principal", help="Manage caller identities (not bearer credentials).")
    identities = principal.add_subparsers(dest="action", required=True)
    identities.add_parser("list")
    new = identities.add_parser("create")
    new.add_argument("name")
    new.add_argument("--id", type=UUID, help="Optional stable UUID; otherwise generate one.")
    access = commands.add_parser("access", help="Manage project grants without deleting events.")
    grants = access.add_subparsers(dest="action", required=True)
    for name in ("list", "grant", "revoke"):
        action = grants.add_parser(name)
        action.add_argument("project_id")
        if name != "list":
            action.add_argument("principal_id", type=UUID)
        if name == "grant":
            action.add_argument("--role", choices=["reader", "writer", "owner"], required=True)


def _metadata(project: Project) -> dict:
    return {"id": project.id, "display_name": project.display_name, "status": project.status}


def manage(args) -> dict:
    settings = Settings.from_env(require_auth=False)
    engine = create_database_engine(settings.database_url)
    try:
        if args.command == "project" and args.action == "create" and args.owner is None:
            token = os.environ.get("CONTITEXT_MCP_TOKEN", "")
            if not token or settings.token_store is None:
                raise AuthenticationError("configure CONTITEXT_MCP_TOKEN and CONTITEXT_AUTH_TOKENS, or supply --owner from principal list")
            from contitext.repository import Repository
            from contitext.schemas import CreateProjectRequest
            from contitext.service import ContextService
            identity = settings.token_store.resolve(token)
            created = ContextService(Repository(create_session_factory(engine))).create_project(
                identity, CreateProjectRequest(project_id=args.project_id, display_name=args.name),
            )
            return {"id": created.project_id, "display_name": created.display_name,
                    "status": created.status, "owner": str(identity.principal_id)}
        with create_session_factory(engine).begin() as session:
            if args.command == "principal":
                if args.action == "list":
                    return {"principals": [{"id": str(p.id), "name": p.name} for p in session.scalars(select(Principal).order_by(Principal.name, Principal.id))]}
                item = SeedPrincipal(id=args.id or uuid4(), name=args.name)
                if session.get(Principal, item.id):
                    raise ValueError("principal already exists")
                session.add(Principal(id=item.id, name=item.name))
                return {"id": str(item.id), "name": item.name}
            if args.command == "project" and args.action == "list":
                return {"projects": [_metadata(p) for p in session.scalars(select(Project).order_by(Project.id))]}
            if args.command == "project" and args.action == "create":
                item = SeedProject(id=args.project_id, display_name=args.name, status="active")
                if session.get(Project, item.id):
                    raise ValueError("project already exists; use project update for metadata changes")
                if session.get(Principal, args.owner) is None:
                    raise ValueError("owner principal does not exist")
                project = Project(**item.model_dump())
                session.add(project)
                session.flush()
                session.add(ProjectACL(project_id=item.id, principal_id=args.owner, role="owner"))
                return {**_metadata(project), "owner": str(args.owner)}
            # Serialize administrative changes to this project's grants and metadata.
            project = session.execute(select(Project).where(Project.id == args.project_id).with_for_update()).scalar_one_or_none()
            if project is None:
                raise ValueError("project does not exist")
            if args.command == "project" and args.action == "update":
                if args.name is None and args.status is None:
                    raise ValueError("provide --name or --status")
                item = SeedProject(id=project.id, display_name=args.name if args.name is not None else project.display_name, status=args.status if args.status is not None else project.status)
                project.display_name, project.status = item.display_name, item.status
                return _metadata(project)
            if args.action in ("list", "show"):
                grants = [{"principal_id": str(acl.principal_id), "name": name, "role": acl.role}
                          for acl, name in session.execute(select(ProjectACL, Principal.name).join(Principal).where(ProjectACL.project_id == args.project_id).order_by(Principal.name, Principal.id))]
                return {**_metadata(project), "access": grants}
            if session.get(Principal, args.principal_id) is None:
                raise ValueError("principal does not exist")
            if args.action == "grant":
                session.execute(insert(ProjectACL).values(project_id=args.project_id, principal_id=args.principal_id, role=args.role).on_conflict_do_update(index_elements=[ProjectACL.project_id, ProjectACL.principal_id], set_={"role": args.role}))
                return {"project_id": args.project_id, "principal_id": str(args.principal_id), "role": args.role}
            result = session.execute(delete(ProjectACL).where(ProjectACL.project_id == args.project_id, ProjectACL.principal_id == args.principal_id))
            return {"project_id": args.project_id, "principal_id": str(args.principal_id), "revoked": bool(result.rowcount)}
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

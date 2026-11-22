"""Idempotent local administration for projects, principals, and ACLs."""

from __future__ import annotations

import argparse
import json
import os
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select, delete, text, exists
from sqlalchemy.exc import SQLAlchemyError

from contitext.auth import AuthenticationError
from contitext.config import ConfigurationError, Settings
from contitext.db import create_database_engine, create_session_factory
from contitext.models import Principal, Project, ProjectACL, Workspace, WorkspaceMember
from contitext.namespaces import ProjectResolver
from contitext.workspaces import create_workspace, workspace_for_admin, change_membership


class SeedProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)?$")
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


class SeedWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    display_name: str = Field(min_length=1)


class SeedMembership(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1)
    principal_id: UUID
    role: Literal["member", "owner"]


class SeedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspaces: list[SeedWorkspace] = Field(default_factory=list)
    memberships: list[SeedMembership] = Field(default_factory=list)
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

    resolver = ProjectResolver()
    workspace_slugs = {item.slug for item in document.workspaces}
    if len(workspace_slugs) != len(document.workspaces):
        raise ValueError("seed contains duplicate workspace slugs")
    memberships = {(item.workspace, item.principal_id) for item in document.memberships}
    if len(memberships) != len(document.memberships):
        raise ValueError("seed contains duplicate memberships")
    if any(item.principal_id not in principal_ids for item in document.memberships):
        raise ValueError("every membership principal must appear in seed principals")
    if any(item.workspace not in workspace_slugs for item in document.memberships):
        raise ValueError("every membership workspace must appear in seed workspaces")
    normalized = [resolver.split(item.id) for item in document.projects]
    if len(set(normalized)) != len(normalized):
        raise ValueError("seed project references resolve to duplicate projects")

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
            if if_empty and document.workspaces and "legacy" not in workspace_slugs:
                # Only discard the empty migration placeholder during a guarded
                # first bootstrap. Never remove a workspace containing data/grants.
                session.execute(delete(Workspace).where(
                    Workspace.id == UUID("00000000-0000-4000-8000-000000000001"), Workspace.slug == "legacy",
                    ~exists(select(Project.id).where(Project.workspace_id == Workspace.id)),
                    ~exists(select(WorkspaceMember.principal_id).where(WorkspaceMember.workspace_id == Workspace.id)),
                ))
            for item in document.principals:
                session.execute(insert(Principal).values(id=item.id, name=item.name).on_conflict_do_update(
                    index_elements=[Principal.id], set_={"name": item.name}))
            for item in document.workspaces:
                workspace = session.scalar(select(Workspace).where(Workspace.slug == item.slug).with_for_update(key_share=True))
                if workspace is None:
                    owners = [m.principal_id for m in document.memberships if m.workspace == item.slug and m.role == "owner"]
                    if not owners:
                        raise ValueError("each new seeded workspace needs an explicit owner membership")
                    workspace = create_workspace(session, item.slug, item.display_name, owners[0])
                else:
                    if not item.display_name.strip():
                        raise ValueError("workspace name must not be blank")
                    workspace.display_name = item.display_name
            for item in sorted(document.memberships, key=lambda m: m.role != "owner"):
                change_membership(session, item.workspace, None, item.principal_id, item.role, operator=True)
            project_map = {}
            for item in document.projects:
                workspace_slug, slug = resolver.split(item.id)
                workspace = session.scalar(select(Workspace).where(Workspace.slug == workspace_slug))
                if workspace is None:
                    raise ValueError("create the workspace before seeding projects")
                project = session.execute(insert(Project).values(
                    id=uuid4(), workspace_id=workspace.id, slug=slug,
                    display_name=item.display_name, status=item.status,
                ).on_conflict_do_update(index_elements=[Project.workspace_id, Project.slug],
                    set_={"display_name": item.display_name, "status": item.status}).returning(Project)).scalar_one()
                project_map[item.id] = project
            for item in document.acls:
                project = project_map[item.project_id]
                # Applying an explicit operator seed provisions membership, never
                # workspace ownership. --if-empty prevents resurrection on restart.
                session.execute(insert(WorkspaceMember).values(
                    workspace_id=project.workspace_id, principal_id=item.principal_id, role="member",
                ).on_conflict_do_nothing())
                session.execute(insert(ProjectACL).values(
                    project_id=project.id, principal_id=item.principal_id, role=item.role,
                ).on_conflict_do_update(index_elements=[ProjectACL.project_id, ProjectACL.principal_id], set_={"role": item.role}))
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

    workspace = commands.add_parser("workspace", help="Manage workspace membership; database operators are trusted.")
    actions = workspace.add_subparsers(dest="action", required=True)
    listing = actions.add_parser("list")
    listing.add_argument("--operator", action="store_true", help="Trusted database operator: list all workspaces.")
    create = actions.add_parser("create")
    create.add_argument("slug")
    create.add_argument("--name", required=True)
    create.add_argument("--owner", type=UUID, help="Trusted operator override; defaults to the authenticated caller.")
    member = actions.add_parser("member")
    member_actions = member.add_subparsers(dest="member_action", required=True)
    for name in ("list", "grant", "revoke"):
        action = member_actions.add_parser(name)
        action.add_argument("slug")
        action.add_argument("--operator", action="store_true", help="Use trusted database operator authority instead of a workspace owner credential.")
        if name != "list":
            action.add_argument("principal_id", type=UUID)
        if name == "grant":
            action.add_argument("--role", choices=["member", "owner"], default="member")


def _metadata(project: Project, workspace: Workspace, resolver: ProjectResolver) -> dict:
    return {"id": resolver.reference(project, workspace), "uuid": str(project.id),
            "workspace": workspace.slug, "display_name": project.display_name, "status": project.status}


def manage(args) -> dict:
    settings = Settings.from_env(require_auth=False)
    engine = create_database_engine(settings.database_url)
    factory = create_session_factory(engine)
    resolver = ProjectResolver()

    def caller():
        token = os.environ.get("CONTITEXT_MCP_TOKEN", "")
        if not token:
            raise AuthenticationError("configure CONTITEXT_MCP_TOKEN or use the explicit trusted operator option")
        return settings.credential_resolver(factory).resolve(token)

    try:
        if args.command == "project" and args.action == "create" and args.owner is None:
            from contitext.repository import Repository
            from contitext.schemas import CreateProjectRequest
            from contitext.service import ContextService
            identity = caller()
            created = ContextService(Repository(factory)).create_project(
                identity, CreateProjectRequest(project_id=args.project_id, display_name=args.name))
            return {"id": created.project_id, "display_name": created.display_name,
                    "status": created.status, "owner": str(identity.principal_id)}
        with factory.begin() as session:
            if args.command == "workspace":
                if args.action == "create":
                    owner = args.owner or caller().principal_id
                    workspace = create_workspace(session, args.slug, args.name, owner)
                    return {"id": str(workspace.id), "slug": workspace.slug, "name": workspace.display_name, "owner": str(owner)}
                identity = None if args.operator else caller().principal_id
                if args.action == "list":
                    statement = select(Workspace)
                    if not args.operator:
                        statement = statement.join(WorkspaceMember).where(WorkspaceMember.principal_id == identity)
                    return {"workspaces": [{"id": str(w.id), "slug": w.slug, "name": w.display_name}
                                           for w in session.scalars(statement.order_by(Workspace.slug))]}
                if args.member_action == "list":
                    workspace = workspace_for_admin(session, args.slug, identity, operator=args.operator)
                    return {"members": [{"principal_id": str(m.principal_id), "role": m.role}
                                        for m in session.scalars(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id).order_by(WorkspaceMember.principal_id))]}
                changed = change_membership(session, args.slug, identity, args.principal_id,
                                            args.role if args.member_action == "grant" else None, operator=args.operator)
                return {"workspace": args.slug, "principal_id": str(args.principal_id), "changed": changed}
            if args.command == "principal":
                if args.action == "list":
                    return {"principals": [{"id": str(p.id), "name": p.name} for p in session.scalars(select(Principal).order_by(Principal.name, Principal.id))]}
                item = SeedPrincipal(id=args.id or uuid4(), name=args.name)
                if session.get(Principal, item.id):
                    raise ValueError("principal already exists")
                session.add(Principal(id=item.id, name=item.name))
                return {"id": str(item.id), "name": item.name}
            if args.command == "project" and args.action == "list":
                return {"projects": [_metadata(p, w, resolver) for p, w in session.execute(select(Project, Workspace).join(Workspace).order_by(Workspace.slug, Project.slug))]}
            workspace_slug, slug = resolver.split(args.project_id)
            workspace = session.scalar(select(Workspace).where(Workspace.slug == workspace_slug))
            if workspace is None:
                raise ValueError("workspace does not exist")
            if args.command == "project" and args.action == "create":
                item = SeedProject(id=args.project_id, display_name=args.name, status="active")
                if session.scalar(select(Project).where(Project.workspace_id == workspace.id, Project.slug == slug)):
                    raise ValueError("project already exists; use project update for metadata changes")
                if session.get(WorkspaceMember, (workspace.id, args.owner)) is None:
                    raise ValueError("owner must be a workspace member")
                project = Project(id=uuid4(), workspace_id=workspace.id, slug=slug, display_name=item.display_name, status=item.status)
                session.add(project)
                session.flush()
                session.add(ProjectACL(project_id=project.id, principal_id=args.owner, role="owner"))
                return {**_metadata(project, workspace, resolver), "owner": str(args.owner)}
            project = session.execute(select(Project).where(Project.workspace_id == workspace.id, Project.slug == slug).with_for_update(key_share=True)).scalar_one_or_none()
            if project is None:
                raise ValueError("project does not exist")
            if args.command == "project" and args.action == "update":
                if args.name is None and args.status is None:
                    raise ValueError("provide --name or --status")
                item = SeedProject(id=args.project_id, display_name=args.name if args.name is not None else project.display_name, status=args.status if args.status is not None else project.status)
                project.display_name, project.status = item.display_name, item.status
                return _metadata(project, workspace, resolver)
            if args.action in ("list", "show"):
                grants = [{"principal_id": str(acl.principal_id), "name": name, "role": acl.role}
                          for acl, name in session.execute(select(ProjectACL, Principal.name).join(Principal).where(ProjectACL.project_id == project.id).order_by(Principal.name, Principal.id))]
                return {**_metadata(project, workspace, resolver), "access": grants}
            if session.get(Principal, args.principal_id) is None:
                raise ValueError("principal does not exist")
            if args.action == "grant":
                member = session.execute(select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.principal_id == args.principal_id,
                ).with_for_update(read=True)).scalar_one_or_none()
                if member is None:
                    raise ValueError("grant workspace membership before project access")
                session.execute(insert(ProjectACL).values(project_id=project.id, principal_id=args.principal_id, role=args.role).on_conflict_do_update(index_elements=[ProjectACL.project_id, ProjectACL.principal_id], set_={"role": args.role}))
                return {"project_id": resolver.reference(project, workspace), "principal_id": str(args.principal_id), "role": args.role}
            result = session.execute(delete(ProjectACL).where(ProjectACL.project_id == project.id, ProjectACL.principal_id == args.principal_id))
            return {"project_id": resolver.reference(project, workspace), "principal_id": str(args.principal_id), "revoked": bool(result.rowcount)}
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

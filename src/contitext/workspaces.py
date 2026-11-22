"""Workspace administration; database/SSH operators remain trusted."""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert

from contitext.models import Principal, Workspace, WorkspaceMember
from contitext.namespaces import validate_slug


class WorkspaceNotFoundError(ValueError):
    pass


def create_workspace(session, slug, display_name, owner):
    validate_slug(slug)
    if not display_name.strip():
        raise ValueError("workspace name must not be blank")
    if session.get(Principal, owner) is None:
        raise ValueError("owner principal does not exist")
    workspace = session.execute(insert(Workspace).values(
        id=uuid4(), slug=slug, display_name=display_name,
    ).on_conflict_do_nothing(index_elements=[Workspace.slug]).returning(Workspace)).scalar_one_or_none()
    if workspace is None:
        raise ValueError("workspace slug is unavailable")
    session.add(WorkspaceMember(workspace_id=workspace.id, principal_id=owner, role="owner"))
    session.flush()
    return workspace


def workspace_for_admin(session, slug, principal_id, *, operator=False):
    # Serialize all membership mutations, including two concurrent last-owner
    # removals. Native operators can repair an unowned migrated workspace.
    workspace = session.execute(select(Workspace).where(
        Workspace.slug == validate_slug(slug),
    ).with_for_update(key_share=True)).scalar_one_or_none()
    membership = session.get(WorkspaceMember, (workspace.id, principal_id)) if workspace and principal_id else None
    if workspace is None or (not operator and (membership is None or membership.role != "owner")):
        raise WorkspaceNotFoundError("workspace not found")
    return workspace


def change_membership(session, slug, actor, target, role, *, operator=False):
    if role not in (None, "member", "owner"):
        raise ValueError("invalid workspace role")
    workspace = workspace_for_admin(session, slug, actor, operator=operator)
    if session.get(Principal, target) is None:
        raise ValueError("principal does not exist")
    existing = session.get(WorkspaceMember, (workspace.id, target))
    if existing is not None and existing.role == "owner" and role != "owner":
        owners = session.scalar(select(func.count()).select_from(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.role == "owner",
        ))
        if owners <= 1:
            raise ValueError("cannot remove or demote the last workspace owner")
    if role is None:
        result = session.execute(delete(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.principal_id == target,
        ))
        return bool(result.rowcount)
    session.execute(insert(WorkspaceMember).values(
        workspace_id=workspace.id, principal_id=target, role=role,
    ).on_conflict_do_update(index_elements=[WorkspaceMember.workspace_id, WorkspaceMember.principal_id], set_={"role": role}))
    return True

"""One project resolver for every transport and human-reading surface."""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from uuid import UUID

from sqlalchemy import select

from contitext.auth import ProjectNotFoundError, ROLE_LEVEL
from contitext.models import Project, ProjectACL, Workspace, WorkspaceMember

SLUG = r"[A-Za-z0-9][A-Za-z0-9._-]*"


def validate_slug(value: str) -> str:
    if not isinstance(value, str) or len(value) > 128 or not re.fullmatch(SLUG, value):
        raise ValueError("invalid slug: use 1–128 letters, digits, dots, underscores or hyphens, starting with a letter or digit")
    return value


def configured_workspace() -> str | None:
    value = os.environ.get("CONTITEXT_COMPATIBILITY_WORKSPACE", "").strip()
    return validate_slug(value) if value else None


@dataclass(frozen=True)
class ResolvedProject:
    project: Project
    workspace: Workspace
    role: str
    reference: str

    @property
    def id(self) -> UUID:
        return self.project.id


class ProjectResolver:
    def __init__(self, compatibility_workspace: str | None = None):
        # An empty string explicitly disables compatibility, including in tests.
        self.compatibility_workspace = (configured_workspace() if compatibility_workspace is None
                                        else validate_slug(compatibility_workspace) if compatibility_workspace else None)

    def split(self, reference: str) -> tuple[str, str]:
        parts = reference.split("/")
        if len(parts) == 1:
            if self.compatibility_workspace is None:
                raise ValueError("use workspace/project; bare IDs require CONTITEXT_COMPATIBILITY_WORKSPACE")
            parts.insert(0, self.compatibility_workspace)
        if len(parts) != 2:
            raise ValueError("use workspace/project")
        return validate_slug(parts[0]), validate_slug(parts[1])

    def reference(self, project: Project, workspace: Workspace) -> str:
        if workspace.slug == self.compatibility_workspace:
            return project.slug
        return f"{workspace.slug}/{project.slug}"

    @staticmethod
    def authorized(principal_id: UUID):
        return (select(Project, Workspace, ProjectACL.role)
                .join(Workspace, Project.workspace_id == Workspace.id)
                .join(WorkspaceMember, (WorkspaceMember.workspace_id == Workspace.id)
                      & (WorkspaceMember.principal_id == principal_id))
                .join(ProjectACL, (ProjectACL.project_id == Project.id)
                      & (ProjectACL.principal_id == principal_id)))

    def _resolve(self, session, principal_id, predicate, minimum_role, *, lock=True):
        if minimum_role not in ROLE_LEVEL:
            raise ValueError(f"unknown required role: {minimum_role}")
        statement = self.authorized(principal_id).where(predicate)
        if lock:
            # SHARE conflicts with both role updates and deletion. A revocation
            # waits for an already-authorized transaction; later calls fail closed.
            statement = statement.with_for_update(read=True, of=(WorkspaceMember, ProjectACL))
        row = session.execute(statement).one_or_none()
        if row is None or ROLE_LEVEL[row[2]] < ROLE_LEVEL[minimum_role]:
            raise ProjectNotFoundError("project not found")
        project, workspace, role = row
        return ResolvedProject(project, workspace, role, self.reference(project, workspace))

    def resolve(self, session, principal_id: UUID, reference: str, minimum_role="reader", *, lock=True):
        workspace, slug = self.split(reference)
        return self._resolve(session, principal_id, (Workspace.slug == workspace) & (Project.slug == slug), minimum_role, lock=lock)

    def resolve_uuid(self, session, principal_id: UUID, project_id: UUID, minimum_role="reader", *, lock=True):
        return self._resolve(session, principal_id, Project.id == project_id, minimum_role, lock=lock)

    def workspace_for_creation(self, session, principal_id: UUID, reference: str):
        workspace_slug, project_slug = self.split(reference)
        row = session.execute(select(Workspace).join(WorkspaceMember).where(
            Workspace.slug == workspace_slug, WorkspaceMember.principal_id == principal_id,
        ).with_for_update(read=True, of=WorkspaceMember)).scalar_one_or_none()
        if row is None:
            raise ProjectNotFoundError("project not found")
        return row, project_slug

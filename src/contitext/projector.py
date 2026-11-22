"""Deterministic Markdown projection through no-follow directory descriptors."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timezone
import inspect
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Callable, Iterator

from sqlalchemy import select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from contitext.auth import PrincipalIdentity
from contitext.namespaces import ProjectResolver
from contitext.locking import acquire_project_transaction_lock
from contitext.models import ContextEvent, ProjectionOffset, ProjectACL
from contitext.schemas import ContextEventResult, ProjectionResult


class ProjectionSafetyError(RuntimeError):
    pass


TARGET_FILES = {
    "note": "NOTES.md",
    "decision": "DECISIONS.md",
    "question": "OPEN-QUESTIONS.md",
    "checkpoint": "STATUS.md",
}


class Projector:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        projects_root: str | Path,
        *,
        filesystem_hook: Callable[[str], None] | None = None,
        legacy_marker_prefixes: tuple[str, ...] = (),
        compatibility_workspace: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self.resolver = ProjectResolver(compatibility_workspace)
        self._projects_root = Path(projects_root).expanduser().absolute()
        self._filesystem_hook = filesystem_hook
        if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", prefix) for prefix in legacy_marker_prefixes):
            raise ProjectionSafetyError("invalid legacy marker prefix")
        self._marker_prefixes = ("contitext", *legacy_marker_prefixes)
        self._require_secure_filesystem_api()

    @staticmethod
    def _require_secure_filesystem_api() -> None:
        if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
            raise ProjectionSafetyError("secure no-follow directory operations are unavailable")
        if any(function not in os.supports_dir_fd for function in (os.open, os.stat, os.unlink)):
            raise ProjectionSafetyError("secure dir_fd filesystem operations are unavailable")
        replace_parameters = inspect.signature(os.replace).parameters
        if "src_dir_fd" not in replace_parameters or "dst_dir_fd" not in replace_parameters:
            raise ProjectionSafetyError("secure relative replace is unavailable")

    def project(self, principal: PrincipalIdentity, project_id: str) -> ProjectionResult:
        changed: list[str] = []
        projected_ids = []
        with self._session_factory.begin() as session:
            project = self.resolver.resolve(session, principal.principal_id, project_id, "owner")
            project_id = project.id
            acquire_project_transaction_lock(session, project_id)
            with self._open_project_dir(project.reference) as project_fd:
                offset = session.get(ProjectionOffset, project_id)
                statement = select(ContextEvent).join(
                    ProjectACL,
                    (ProjectACL.project_id == ContextEvent.project_id)
                    & (ProjectACL.principal_id == principal.principal_id),
                ).where(ContextEvent.project_id == project_id)
                if offset and offset.last_event_created_at is not None and offset.last_event_id is not None:
                    statement = statement.where(
                        tuple_(ContextEvent.created_at, ContextEvent.event_id)
                        > tuple_(offset.last_event_created_at, offset.last_event_id)
                    )
                events = list(session.execute(statement.order_by(
                    ContextEvent.created_at.asc(), ContextEvent.event_id.asc()
                )).scalars())

                for event in events:
                    relative = self._project_event(project_fd, event, project.reference)
                    if relative is not None:
                        changed.append(relative)
                    projected_ids.append(event.event_id)

                if events:
                    last = events[-1]
                    session.execute(
                        insert(ProjectionOffset)
                        .values(
                            project_id=project_id,
                            last_event_created_at=last.created_at,
                            last_event_id=last.event_id,
                        )
                        .on_conflict_do_update(
                            index_elements=[ProjectionOffset.project_id],
                            set_={
                                "last_event_created_at": last.created_at,
                                "last_event_id": last.event_id,
                                "updated_at": text("CURRENT_TIMESTAMP"),
                            },
                        )
                    )
                    last_created_at = last.created_at
                    last_event_id = last.event_id
                elif offset:
                    last_created_at = offset.last_event_created_at
                    last_event_id = offset.last_event_id
                else:
                    last_created_at = None
                    last_event_id = None

        return ProjectionResult(
            project_id=project.reference,
            projected_event_ids=projected_ids,
            files_changed=sorted(set(changed)),
            last_event_created_at=last_created_at,
            last_event_id=last_event_id,
        )

    @contextmanager
    def _open_project_dir(self, project_id: str) -> Iterator[int]:
        parts = project_id.split("/")
        if len(parts) > 2 or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", p) for p in parts):
            raise ProjectionSafetyError("unsafe project path")
        directory_fd = self._open_absolute_directory(self._projects_root, "projects root")
        try:
            for part in parts:
                next_fd = self._open_child_directory(directory_fd, part, f"project {project_id}")
                os.close(directory_fd)
                directory_fd = next_fd
            if self._filesystem_hook is not None:
                self._filesystem_hook("project")
            yield directory_fd
        finally:
            os.close(directory_fd)

    def _open_absolute_directory(self, path: Path, label: str) -> int:
        if not path.is_absolute():
            raise ProjectionSafetyError(f"unsafe {label}: expected absolute path")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        current_fd = -1
        try:
            current_fd = os.open("/", flags)
            for part in path.parts[1:]:
                if part in ("", ".", ".."):
                    raise ProjectionSafetyError(f"unsafe {label}: invalid path component")
                next_fd = os.open(part, flags, dir_fd=current_fd)
                os.close(current_fd)
                current_fd = next_fd
            return current_fd
        except ProjectionSafetyError:
            if current_fd >= 0:
                os.close(current_fd)
            raise
        except OSError as exc:
            if current_fd >= 0:
                os.close(current_fd)
            raise ProjectionSafetyError(f"unsafe {label}: {exc}") from exc

    @staticmethod
    def _open_child_directory(parent_fd: int, name: str, label: str) -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            return os.open(name, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise ProjectionSafetyError(f"unsafe {label}: {exc}") from exc

    def _project_event(self, project_fd: int, event: ContextEvent, reference: str) -> str | None:
        from contitext.repository import Repository
        rendered = render_event(Repository._event_result(event, reference))
        markers = [f"<!-- {prefix}:event:{event.event_id}:begin -->" for prefix in self._marker_prefixes]
        if event.event_kind == "handoff":
            handoffs_fd = self._open_child_directory(project_fd, "HANDOFFS", "HANDOFFS")
            try:
                if self._filesystem_hook is not None:
                    self._filesystem_hook("handoffs")
                target = f"{event.event_id}.md"
                if self._entry_exists(handoffs_fd, target, "handoff target"):
                    existing = self._read_file(handoffs_fd, target, "handoff target")
                    if any(marker in existing for marker in markers):
                        return None
                    raise ProjectionSafetyError("handoff target already exists with different content")
                self._atomic_write(handoffs_fd, target, "# Handoff\n\n" + rendered, "handoff target")
                return f"HANDOFFS/{target}"
            finally:
                os.close(handoffs_fd)

        filename = TARGET_FILES[event.event_kind]
        existing = self._read_file(project_fd, filename, filename)
        if any(marker in existing for marker in markers):
            return None
        separator = "" if existing.endswith("\n") or not existing else "\n"
        self._atomic_write(project_fd, filename, existing + separator + "\n" + rendered, filename)
        return filename

    @staticmethod
    def _entry_exists(directory_fd: int, name: str, label: str) -> bool:
        try:
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise ProjectionSafetyError(f"unsafe {label}: {exc}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise ProjectionSafetyError(f"unsafe {label}: symlink is not allowed")
        if not stat.S_ISREG(info.st_mode):
            raise ProjectionSafetyError(f"unsafe {label}: expected regular file")
        return True

    @staticmethod
    def _read_file(directory_fd: int, name: str, label: str) -> str:
        Projector._entry_exists(directory_fd, name, label)
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        except OSError as exc:
            raise ProjectionSafetyError(f"could not safely read {label}: {exc}") from exc
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ProjectionSafetyError(f"unsafe {label}: expected regular file")
            with os.fdopen(fd, "r", encoding="utf-8") as handle:
                fd = -1
                return handle.read()
        finally:
            if fd >= 0:
                os.close(fd)

    @staticmethod
    def _atomic_write(directory_fd: int, name: str, content: str, label: str) -> None:
        Projector._entry_exists(directory_fd, name, label)
        temporary = ""
        fd = -1
        try:
            for _ in range(100):
                temporary = f".{name}.{secrets.token_hex(12)}.tmp"
                try:
                    fd = os.open(
                        temporary,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=directory_fd,
                    )
                    break
                except FileExistsError:
                    continue
            else:
                raise ProjectionSafetyError(f"could not exclusively create temporary {label}")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = -1
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            Projector._entry_exists(directory_fd, name, label)
            os.replace(
                temporary,
                name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            temporary = ""
            Projector._entry_exists(directory_fd, name, label)
            os.fsync(directory_fd)
        except OSError as exc:
            raise ProjectionSafetyError(f"could not safely write {label}: {exc}") from exc
        finally:
            if fd >= 0:
                os.close(fd)
            if temporary:
                try:
                    os.unlink(temporary, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass


def render_event(event: ContextEventResult) -> str:
    timestamp = event.created_at.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    payload = json.dumps(event.payload, ensure_ascii=False, indent=2, sort_keys=True)
    return (
        f"<!-- contitext:event:{event.event_id}:begin -->\n"
        f"## {event.event_kind.value} — {timestamp}\n"
        f"- event_id: `{event.event_id}`\n"
        f"- project_id: `{event.project_id}`\n"
        f"- principal_id: `{event.principal_id}`\n"
        f"- scope_id: `{event.scope_id}`\n"
        f"- session_id: `{event.session_id}`\n"
        f"- agent_id: `{event.agent_id}`\n"
        f"- source_kind: `{event.source_kind}`\n"
        f"- source_id: `{event.source_id}`\n\n"
        f"```json\n{payload}\n```\n"
        + ("Context metadata: " + event.event_metadata.model_dump_json() + "\n" if event.event_metadata else "")
        +
        f"<!-- contitext:event:{event.event_id}:end -->\n"
    )

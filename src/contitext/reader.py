"""Read-only database snapshots for a dedicated Markdown/Obsidian reading folder."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import re
import stat
import time

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from contitext.auth import AuthenticationError, ProjectNotFoundError
from contitext.config import Settings
from contitext.db import create_database_engine, create_session_factory
from contitext.models import ContextEvent, Principal, Project, ProjectACL
from contitext.projector import Projector, ProjectionSafetyError

MANIFEST = ".contitext-reader.json"
FORMAT = "contitext-reader-v1"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def literal(value) -> str:
    """Keep stored content readable without activating HTML, links, or embeds."""
    value = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(value))
    value = html.escape(value, quote=False)
    return re.sub(r"([\\`*_{}\[\]()!#|])", r"\\\1", value).replace("\n", "\n  ")


def project_filename(project_id: str) -> str:
    label = re.sub(r"[^a-z0-9._-]", "-", project_id.lower())[:60].strip(".") or "project"
    digest = hashlib.sha256(project_id.encode()).hexdigest()[:16]
    return f"project-{label}--{digest}.md"


def snapshot(engine, identity, project_ids: list[str] | None = None) -> list[dict]:
    """Read ACLs and events from one consistent PostgreSQL read-only transaction."""
    with create_session_factory(engine)() as session, session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        if session.get(Principal, identity.principal_id) is None:
            raise AuthenticationError("authenticated principal is not provisioned")
        from contitext.namespaces import ProjectResolver
        resolver = ProjectResolver()
        rows = session.execute(resolver.authorized(identity.principal_id).order_by(Project.id)).all()
        selected = {p.id for p, _, _ in rows}
        if project_ids is not None:
            selected = {resolver.resolve(session, identity.principal_id, ref, lock=False).id for ref in project_ids}
        events = defaultdict(list)
        if selected:
            for e in session.scalars(select(ContextEvent).where(
                ContextEvent.project_id.in_(selected),
            ).order_by(ContextEvent.created_at, ContextEvent.event_id)):
                events[e.project_id].append({
                    "id": str(e.event_id), "kind": e.event_kind, "payload": e.payload,
                    "event_metadata": e.event_metadata,
                    "created_at": e.created_at.astimezone(timezone.utc).isoformat(),
                    "agent_id": e.agent_id, "source_kind": e.source_kind, "source_id": e.source_id,
                })
        return sorted([{"id": resolver.reference(p, w), "name": p.display_name, "status": p.status, "role": role,
                        "events": events[p.id]} for p, w, role in rows if p.id in selected], key=lambda p: p["id"])


def render_payload(payload: dict) -> str:
    lines = []
    for key, value in payload.items():
        label = literal(key.replace("_", " ").capitalize())
        if isinstance(value, list):
            lines.append(f"**{label}:**")
            lines.extend(f"- {literal(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))}" for v in value)
            if not value:
                lines.append("- None recorded.")
        elif isinstance(value, dict):
            lines.append(f"**{label}:** {literal(json.dumps(value, ensure_ascii=False))}")
        else:
            lines.append(f"**{label}:** {literal(value)}")
        lines.append("")
    return "\n".join(lines) or "No content recorded.\n"


def render_event(event: dict, heading: str) -> str:
    return (f"### {heading} — {literal(event['created_at'])}\n\n"
            + ("**Context metadata:** " + literal(json.dumps(event["event_metadata"])) + "\n\n" if event.get("event_metadata") else "")
            + render_payload(event["payload"])
            + f"\nRecorded by {literal(event['agent_id'])}. Event: `{event['id']}`.\n\n"
            + f"Source: {literal(event['source_kind'])} / {literal(event['source_id'])}.\n\n")


def render(projects: list[dict], generated_at: str) -> dict[str, str]:
    files = {}
    index = ["# Contitext project reader", "",
             f"Last successful database snapshot: **{generated_at}**.", "",
             "[Refresh status](SYNC-STATUS.md) · Generated reading copy; the database remains authoritative.", "",
             "Open a project below to read its latest checkpoint, latest handoff, and event history.", "",
             "These pages refresh automatically only while an exporter is running. Edits here are not imported and will be replaced.", "",
             "## Projects", ""]
    for project in projects:
        filename = project_filename(project["id"])
        if filename in files:
            raise ValueError("project filenames collide; choose another export selection")
        index.append(f"- [{literal(project['name'])}]({filename}) — `{literal(project['id'])}` · {literal(project['status'])} · {literal(project['role'])} · {len(project['events'])} events")
        lines = [f"# {literal(project['name'])}", "", "[All projects](README.md) · [Refresh status](SYNC-STATUS.md)", "",
                 f"Project ID: `{literal(project['id'])}` · Status: {literal(project['status'])} · Access: {literal(project['role'])}", "",
                 f"Database snapshot: {generated_at}. This generated page is replaced on refresh.", "",
                 "## Latest recorded state", ""]
        events = project["events"]
        for kind, label in [("checkpoint", "Latest checkpoint"), ("handoff", "Latest handoff")]:
            latest = next((e for e in reversed(events) if e["kind"] == kind and not (e.get("event_metadata") or {}).get("candidate")), None)
            lines.append(render_event(latest, label) if latest else f"### {label}\n\nNone recorded.\n")
        lines.extend(["## Event history", "", "Newest first. History includes resolved questions and superseded decisions. Lifecycle changes require explicit metadata; candidate progress is not verified state.", ""])
        for kind, title in [("decision", "Decisions"), ("question", "Questions"), ("note", "Notes"), ("checkpoint", "Checkpoints"), ("handoff", "Handoffs")]:
            lines.extend([f"## {title}", ""])
            matching = [e for e in reversed(events) if e["kind"] == kind]
            lines.extend(render_event(e, kind.capitalize()) for e in matching)
            if not matching:
                lines.append("None recorded.\n")
        files[filename] = "\n".join(lines) + "\n"
    if not projects:
        index.append("No projects are accessible to the configured identity.")
    files["README.md"] = "\n".join(index) + "\n"
    return files


def managed_filename(name) -> bool:
    return isinstance(name, str) and (name == "README.md" or bool(re.fullmatch(r"project-[a-z0-9._-]+--[a-f0-9]{16}\.md", name)))


class ReaderDirectory:
    """Own generated files only; reject symlinks, unrelated folders, and parallel writers."""
    def __init__(self, output: Path, principal_id: str):
        Projector._require_secure_filesystem_api()
        self.path = output.expanduser().absolute()
        self.principal_id = principal_id
        self.fd = self.lock_fd = -1
        helper = object.__new__(Projector)
        parent = helper._open_absolute_directory(self.path.parent, "reader parent")
        try:
            try:
                os.mkdir(self.path.name, mode=0o700, dir_fd=parent)
            except FileExistsError:
                pass
            self.fd = Projector._open_child_directory(parent, self.path.name, "reader output")
        finally:
            os.close(parent)
        try:
            names = set(os.listdir(self.fd))
            if MANIFEST not in names and names - {".obsidian", ".contitext-reader.lock"}:
                raise ValueError("reader output must be empty or an existing Contitext reader folder")
            self.lock_fd = os.open(".contitext-reader.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
            if not stat.S_ISREG(os.fstat(self.lock_fd).st_mode):
                raise ValueError("invalid reader lock")
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("another exporter owns this reader folder") from exc
            if Projector._entry_exists(self.fd, MANIFEST, MANIFEST):
                self.manifest = json.loads(Projector._read_file(self.fd, MANIFEST, MANIFEST))
                if (not isinstance(self.manifest, dict) or self.manifest.get("format") != FORMAT or self.manifest.get("principal_id") != principal_id
                        or not isinstance(self.manifest.get("files"), list)
                        or not all(managed_filename(n) for n in self.manifest["files"])):
                    raise ValueError("reader manifest is invalid or belongs to another identity")
            else:
                self.manifest = {"format": FORMAT, "principal_id": principal_id, "files": [], "last_success": None}
                self.write(MANIFEST, json.dumps(self.manifest, indent=2) + "\n")
        except BaseException:
            self.close()
            raise

    def write(self, name, content):
        Projector._atomic_write(self.fd, name, content, name)

    def publish(self, projects: list[dict]):
        generated_at = utcnow()
        files = render(projects, generated_at)
        previous = set(self.manifest["files"])
        # Journal ownership before publishing: interrupted refreshes remain cleanable.
        self.manifest.update(files=sorted(previous | files.keys()), pending=True)
        self.write(MANIFEST, json.dumps(self.manifest, indent=2) + "\n")
        self.status("Refreshing; the previous complete refresh is listed below.")
        for name, content in files.items():
            self.write(name, content)
        for name in previous - files.keys():
            if Projector._entry_exists(self.fd, name, name):
                os.unlink(name, dir_fd=self.fd)
        self.manifest.update(files=sorted(files), pending=False, last_success=generated_at,
                             projects=len(projects), events=sum(len(p["events"]) for p in projects))
        self.write(MANIFEST, json.dumps(self.manifest, indent=2) + "\n")
        self.status("OK")
        return {"status": "ok", "output": str(self.path), "snapshot_at": generated_at,
                "projects": self.manifest["projects"], "events": self.manifest["events"]}

    def status(self, message):
        self.write("SYNC-STATUS.md", "# Reader refresh status\n\n"
                   f"Status: **{message}**\n\nLast attempt: {utcnow()}.\n\n"
                   f"Last successful database snapshot: {self.manifest.get('last_success') or 'Never'}.\n\n"
                   "If this timestamp stops advancing, check the exporter or its supervisor. A stopped process cannot report its own failure.\n\n"
                   "Remote copies can lag behind this snapshot; check the local transfer status too.\n")

    def close(self):
        if self.lock_fd >= 0:
            os.close(self.lock_fd); self.lock_fd = -1
        if self.fd >= 0:
            os.close(self.fd); self.fd = -1


def run(args) -> int:
    settings = Settings.from_env()
    engine = create_database_engine(settings.database_url)
    output = None
    try:
        resolver = settings.credential_resolver(create_session_factory(engine))
        token = os.environ.get("CONTITEXT_MCP_TOKEN", "")
        identity = resolver.resolve(token)
        output = ReaderDirectory(args.output, str(identity.principal_id))
        while True:
            try:
                identity = resolver.resolve(token)
                fence = os.environ.get("CONTITEXT_WRITER_FENCE_FILE")
                if fence and Path(fence).exists():
                    raise ValueError("maintenance")
                result = output.publish(snapshot(engine, identity, args.project))
            except (SQLAlchemyError, AuthenticationError, ProjectNotFoundError, ValueError, OSError, ProjectionSafetyError):
                # Connection errors may contain credentials: emit only a fixed diagnostic.
                output.status("Refresh failed. Previous files may be stale; check configuration, access, storage, and maintenance status.")
                result = {"status": "error", "message": "reader refresh failed; no database data was changed"}
                print(json.dumps(result), flush=True)
                if not args.watch:
                    return 1
            else:
                print(json.dumps(result), flush=True)
                if not args.watch:
                    return 0
            time.sleep(args.watch)
    except KeyboardInterrupt:
        return 0
    finally:
        if output is not None:
            output.close()
        engine.dispose()

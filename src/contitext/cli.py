"""Public command line entry points, including migrations in installed wheels."""

from __future__ import annotations

import argparse
import json
import os
import sys
from importlib.metadata import version
from pathlib import Path


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    command.upgrade(config, "head")


def serve() -> None:
    """Compatibility entry point for the original contitext-api executable."""
    main(["serve", *sys.argv[1:]])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="contitext", description="Project continuity for AI agents.",
    )
    parser.add_argument("--version", action="version", version=version("contitext"))
    parser.add_argument("--env-file", type=Path, action="append", default=[], help="Explicit dotenv file; repeat for ordered overrides. Never loaded implicitly.")
    commands = parser.add_subparsers(dest="command", required=True)
    from contitext.onboarding import add_arguments
    add_arguments(commands.add_parser("init", help="Create private configuration and an initial project seed."))
    from contitext.admin import add_management_commands
    add_management_commands(commands)
    from contitext.credentials import add_arguments as add_credentials
    add_credentials(commands)
    hooks = commands.add_parser("hooks", help="Install opt-in session start hooks.")
    hook_commands = hooks.add_subparsers(dest="hook_action", required=True)
    hook_install = hook_commands.add_parser("install")
    from contitext.hook_contracts import CLIENTS
    hook_install.add_argument("--client", choices=CLIENTS, required=True)
    hook_install.add_argument("--config", type=Path, required=True, help="Explicit client hooks/settings JSON to merge.")
    hook_install.add_argument("--connection", type=Path, required=True)
    hook_install.add_argument("--mappings", type=Path, required=True)
    hook_install.add_argument("--dry-run", action="store_true")
    hook_install.add_argument("--checkpoints", action="store_true", help="Opt in to candidate progress capture and durable retry.")
    hook_install.add_argument("--state-dir", type=Path)
    hook_status = hook_commands.add_parser("status")
    hook_status.add_argument("--state-dir", type=Path, required=True)
    for action in ("flush", "checkpoint"):
        operation = hook_commands.add_parser(action)
        operation.add_argument("--client", choices=CLIENTS, required=True)
        operation.add_argument("--connection", type=Path, required=True)
        operation.add_argument("--mappings", type=Path, required=True)
        operation.add_argument("--state-dir", type=Path, required=True)
        operation.add_argument("--session-id", required=True)
        operation.add_argument("--conversation-id", help="Required stable conversation ID for Cursor.")
        operation.add_argument("--source-id", help="Stable milestone identifier for an explicit intermediate candidate.")
        operation.add_argument("--task-id")

    mappings = commands.add_parser("mapping", help="Manage explicit local workspace/project mappings.")
    mapping_commands = mappings.add_subparsers(dest="mapping_action", required=True)
    for action in ("add", "list", "remove"):
        mapping = mapping_commands.add_parser(action)
        mapping.add_argument("--mappings", type=Path, required=True, help="Explicit absolute private mapping file; never discovered from a repository.")
        mapping.add_argument("--connection", type=Path, required=True, help="Trusted command/args MCP connection JSON.")
        if action != "list":
            selector = mapping.add_mutually_exclusive_group(required=True)
            selector.add_argument("--remote")
            selector.add_argument("--directory", type=Path)
        if action == "add":
            mapping.add_argument("--project", required=True, help="Qualified workspace/project reference.")
    resolve = commands.add_parser("resolve", help="Preview an authorized explicit mapping; optionally bind only an unbound scope.")
    resolve.add_argument("--mappings", type=Path, required=True)
    resolve.add_argument("--connection", type=Path, required=True)
    resolve.add_argument("--cwd", type=Path, required=True)
    resolve.add_argument("--scope-id", required=True)
    resolve.add_argument("--session-id", required=True)
    resolve.add_argument("--bind", action="store_true", help="Opt in to atomic bind-if-unbound; never replace an existing binding.")
    resolve.add_argument("--timeout", type=float, default=5, help="Total connection/resolve timeout in seconds (0.1–30).")
    reader = commands.add_parser("export", help="Export an authenticated Markdown reading copy without changing the database.")
    reader.add_argument("--output", type=Path, required=True, help="Dedicated empty or managed reading folder; parent must exist.")
    reader.add_argument("--project", action="append", help="Explicit project ID; repeat to select several. Default: all accessible projects.")
    reader.add_argument("--watch", type=int, metavar="SECONDS", help="Refresh repeatedly; minimum 10 seconds. Otherwise export once.")
    upgrade = commands.add_parser("upgrade-check", help="Read-only upgrade inventory and integrity comparison; does not migrate or fence writers.")
    snapshot = upgrade.add_mutually_exclusive_group()
    snapshot.add_argument("--snapshot", type=Path, help="Save a new private integrity baseline; refuses to overwrite.")
    snapshot.add_argument("--compare", type=Path, help="Compare normalized data and effective permissions with a saved baseline.")
    commands.add_parser("doctor", help="Check configuration, database, MCP identity, and access without writing.")
    client = commands.add_parser("client-config", help="Print generic MCP client JSON without embedding secrets.")
    transport = client.add_mutually_exclusive_group(required=True)
    transport.add_argument("--compose", help="Absolute Compose directory on the server.")
    transport.add_argument("--config-file", help="Absolute dotenv path on the server.")
    client.add_argument("--executable", default="contitext", help="Installed executable path on the server.")
    client.add_argument("--ssh", help="Optional existing SSH host alias or user@host.")
    client.add_argument("--compose-project", help="Compose project name when deployment uses --project-name/-p.")
    client.add_argument("--credential-file", help="Absolute private token dotenv path on the server; overrides the shared client's token.")
    commands.add_parser("migrate", help="Apply database migrations.")
    api = commands.add_parser("serve", help="Run the REST API.")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    commands.add_parser("mcp", help="Run the stdio MCP server.")
    commands.add_parser(
        "mcp-smoke", help="Check all eight MCP tools using synthetic data.",
        description="Check MCP in a test deployment; writes synthetic records and creates a project.",
    )
    admin = commands.add_parser("admin", help="Administer projects, principals, and access.")
    admin_commands = admin.add_subparsers(dest="admin_command", required=True)
    seed = admin_commands.add_parser("seed", help="Apply the configured seed document.")
    seed.add_argument("--if-empty", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "resolve" and not 0.1 <= args.timeout <= 30:
        parser.error("--timeout must be between 0.1 and 30 seconds")
    if args.command == "export" and args.watch is not None and args.watch < 10:
        parser.error("--watch must be at least 10 seconds")
    for env_file in args.env_file:
        from dotenv import dotenv_values
        if not env_file.is_file():
            parser.error("configuration file does not exist")
        try:
            values = dotenv_values(env_file, interpolate=False)
        except (OSError, UnicodeError):
            parser.error("cannot read configuration file")
        os.environ.update({key: value for key, value in values.items() if value is not None})
    if args.command == "hooks":
        from contitext.hook_config import install
        from contitext.resolution import ResolutionError
        try:
            if args.hook_action == "install":
                result = install(args)
            elif args.hook_action == "status":
                from contitext.outbox import status
                result = status(args.state_dir)
            else:
                from contitext.hooks import run_supervised
                from contitext.outbox import stage, status
                args.timeout, args.max_bytes = 3, 12000
                event = {"hook_event_name":"Checkpoint", "session_id":args.session_id}
                if args.client == 'cursor':
                    if not args.conversation_id:
                        raise ResolutionError('Cursor checkpoint/flush requires --conversation-id')
                    event['conversation_id'] = args.conversation_id
                if args.hook_action == "checkpoint":
                    if not args.source_id:
                        raise ResolutionError("checkpoint requires --source-id")
                    summary = sys.stdin.read(65537)
                    if len(summary.encode()) > 65536 or not summary.strip():
                        raise ResolutionError("provide a nonempty bounded summary on stdin")
                    event.update(last_assistant_message=summary, source_id=args.source_id)
                    if stage(args,event) is None:
                        raise ResolutionError("no captured binding; start the session with the configured hook first")
                run_supervised(args, json.dumps(event).encode())
                result = status(args.state_dir)
            print(json.dumps(result, indent=2))
        except ResolutionError as exc:
            parser.error(str(exc))
        except OSError:
            parser.error("hook configuration failed; check trusted paths, permissions and existing hooks")
        return
    if args.command in {"mapping", "resolve"}:
        import asyncio
        from contitext.resolution import ResolutionError, edit_mapping
        from contitext.session_client import resolve_command
        try:
            result = edit_mapping(args) if args.command == "mapping" else asyncio.run(resolve_command(args))
        except ResolutionError as exc:
            parser.error(str(exc))
        print(json.dumps(result, sort_keys=True))
        if args.command == "resolve" and result["status"] in {"unmatched", "ambiguous"}:
            raise SystemExit(1)
        return
    if args.command == "export":
        from contitext.reader import run
        from contitext.auth import AuthenticationError
        from contitext.config import ConfigurationError
        from contitext.projector import ProjectionSafetyError
        try:
            raise SystemExit(run(args))
        except (AuthenticationError, ConfigurationError, ValueError, OSError, ProjectionSafetyError):
            parser.error("cannot start reader; check authentication, output ownership, permissions, and configuration")
    if args.command in {"init", "upgrade-check", "workspace", "project", "principal", "access", "credential", "doctor", "client-config"}:
        from contitext.admin import manage
        from contitext.config import ConfigurationError
        from contitext.auth import AuthenticationError, ProjectNotFoundError
        from contitext.repository import ProjectCreationConflictError
        from contitext.service import WriterFencedError
        from contitext.diagnostics import doctor, client_config
        from contitext.onboarding import initialize
        from pydantic import ValidationError
        from sqlalchemy.exc import SQLAlchemyError
        try:
            if args.command == "init":
                result = initialize(args)
            elif args.command == "upgrade-check":
                from contitext.upgrade import inspect_upgrade, compare_snapshot, write_snapshot
                from contitext.config import Settings
                result = inspect_upgrade(Settings.from_env(require_auth=False).database_url)
                if args.compare:
                    compare_snapshot(result, args.compare)
                if args.snapshot:
                    write_snapshot(result, args.snapshot)
            elif args.command == "doctor":
                result = doctor()
            elif args.command == "client-config":
                result = client_config(args)
            elif args.command == "credential":
                from contitext.credentials import manage as manage_credentials
                from contitext.config import Settings
                from contitext.db import create_database_engine, create_session_factory
                settings = Settings.from_env(require_auth=False)
                engine = create_database_engine(settings.database_url)
                try:
                    result = manage_credentials(args, create_session_factory(engine))
                    if settings.auth_mode == "config" and args.action in {"revoke", "rotate"}:
                        result["warning"] = "Database credentials changed only. Config-mode services still require token removal from configuration and restart."
                finally:
                    engine.dispose()
            else:
                result = manage(args)
        except FileExistsError:
            parser.error("upgrade snapshot already exists; preserved without changes" if args.command == "upgrade-check" else "configuration already exists; preserved without changes")
        except ValidationError:
            parser.error("invalid identifier or empty name; check command arguments")
        except (ValueError, ConfigurationError, AuthenticationError, ProjectNotFoundError, ProjectCreationConflictError, WriterFencedError) as exc:
            parser.error(str(exc))
        except SQLAlchemyError:
            parser.error("database operation failed; check connectivity, migrations, and identifiers")
        except OSError:
            parser.error("cannot access configuration output; check directory and permissions")
        print(json.dumps(result, sort_keys=True))
        if args.command in {"doctor", "upgrade-check"} and not result["ok"]:
            raise SystemExit(1)
        return
    if args.command == "migrate":
        migrate()
    elif args.command == "serve":
        import uvicorn

        uvicorn.run(
            "contitext.api:app_from_env", factory=True, host=args.host, port=args.port,
            access_log=False,
        )
    elif args.command == "mcp":
        from contitext.mcp_server import main as run_mcp

        run_mcp()
    elif args.command == "mcp-smoke":
        from contitext.mcp_smoke import main as run_smoke

        run_smoke()
    elif args.command == "admin":
        from contitext.admin import main as run_admin

        run_admin([args.admin_command, *(["--if-empty"] if args.if_empty else [])], prog="contitext admin")


if __name__ == "__main__":
    main()

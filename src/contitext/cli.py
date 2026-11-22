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
    parser.add_argument("--env-file", type=Path, help="Explicit dotenv configuration file; never loaded implicitly.")
    commands = parser.add_subparsers(dest="command", required=True)
    from contitext.onboarding import add_arguments
    add_arguments(commands.add_parser("init", help="Create private configuration and an initial project seed."))
    from contitext.admin import add_management_commands
    add_management_commands(commands)
    from contitext.credentials import add_arguments as add_credentials
    add_credentials(commands)
    reader = commands.add_parser("export", help="Export an authenticated Markdown reading copy without changing the database.")
    reader.add_argument("--output", type=Path, required=True, help="Dedicated empty or managed reading folder; parent must exist.")
    reader.add_argument("--project", action="append", help="Explicit project ID; repeat to select several. Default: all accessible projects.")
    reader.add_argument("--watch", type=int, metavar="SECONDS", help="Refresh repeatedly; minimum 10 seconds. Otherwise export once.")
    commands.add_parser("doctor", help="Check configuration, database, MCP identity, and access without writing.")
    client = commands.add_parser("client-config", help="Print generic MCP client JSON without embedding secrets.")
    transport = client.add_mutually_exclusive_group(required=True)
    transport.add_argument("--compose", help="Absolute Compose directory on the server.")
    transport.add_argument("--config-file", help="Absolute dotenv path on the server.")
    client.add_argument("--executable", default="contitext", help="Installed executable path on the server.")
    client.add_argument("--ssh", help="Optional existing SSH host alias or user@host.")
    client.add_argument("--compose-project", help="Compose project name when deployment uses --project-name/-p.")
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
    if args.command == "export" and args.watch is not None and args.watch < 10:
        parser.error("--watch must be at least 10 seconds")
    if args.env_file:
        from dotenv import dotenv_values
        if not args.env_file.is_file():
            parser.error("configuration file does not exist")
        try:
            values = dotenv_values(args.env_file, interpolate=False)
        except (OSError, UnicodeError):
            parser.error("cannot read configuration file")
        os.environ.update({key: value for key, value in values.items() if value is not None})
    if args.command == "export":
        from contitext.reader import run
        from contitext.auth import AuthenticationError
        from contitext.config import ConfigurationError
        from contitext.projector import ProjectionSafetyError
        try:
            raise SystemExit(run(args))
        except (AuthenticationError, ConfigurationError, ValueError, OSError, ProjectionSafetyError):
            parser.error("cannot start reader; check authentication, output ownership, permissions, and configuration")
    if args.command in {"init", "workspace", "project", "principal", "access", "credential", "doctor", "client-config"}:
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
            parser.error("configuration already exists; preserved without changes")
        except ValidationError:
            parser.error("invalid identifier or empty name; check command arguments")
        except (ValueError, ConfigurationError, AuthenticationError, ProjectNotFoundError, ProjectCreationConflictError, WriterFencedError) as exc:
            parser.error(str(exc))
        except SQLAlchemyError:
            parser.error("database operation failed; check connectivity, migrations, and identifiers")
        except OSError:
            parser.error("cannot access configuration output; check directory and permissions")
        print(json.dumps(result, sort_keys=True))
        if args.command == "doctor" and not result["ok"]:
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

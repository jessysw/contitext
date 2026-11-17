"""Public command line entry points, including migrations in installed wheels."""

from __future__ import annotations

import argparse
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
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="Apply database migrations.")
    api = commands.add_parser("serve", help="Run the REST API.")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    commands.add_parser("mcp", help="Run the stdio MCP server.")
    commands.add_parser(
        "mcp-smoke", help="Check all six MCP tools using synthetic records.",
        description="Check MCP against CONTITEXT_SMOKE_PROJECT_ID; writes synthetic records.",
    )
    admin = commands.add_parser("admin", help="Administer projects, principals, and access.")
    admin_commands = admin.add_subparsers(dest="admin_command", required=True)
    admin_commands.add_parser("seed", help="Apply the configured seed document.")
    args = parser.parse_args(argv)
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

        run_admin([args.admin_command], prog="contitext admin")


if __name__ == "__main__":
    main()

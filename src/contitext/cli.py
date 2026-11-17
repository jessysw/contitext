"""Public command line entry points, including migrations in installed wheels."""

from __future__ import annotations

import argparse
from importlib.metadata import version
from pathlib import Path


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    command.upgrade(config, "head")


def serve() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(prog="contitext-api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("contitext.api:app_from_env", factory=True, host=args.host, port=args.port,
                access_log=False)


def main() -> None:
    parser = argparse.ArgumentParser(prog="contitext")
    parser.add_argument("--version", action="version", version=version("contitext"))
    parser.add_argument("command", choices=["migrate", "mcp"])
    args = parser.parse_args()
    if args.command == "migrate":
        migrate()
    else:
        from contitext.mcp_server import main as run_mcp
        run_mcp()


if __name__ == "__main__":
    main()

"""Exercise the public CLI without relying on a source-checkout working directory."""

import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from sqlalchemy import create_engine, text

from contitext import __version__


TEST_AUTH = json.dumps({
    "cli-test-only": {"principal_id": "55555555-5555-4555-8555-555555555555", "name": "CLI Owner"},
})
BIN_DIR = Path(sys.executable).parent


def cli(*args, cwd, env=None):
    executable = BIN_DIR / "contitext"
    assert executable.is_file(), "The package console script must be installed"
    return subprocess.run(
        [executable, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=20,
    )


@pytest.mark.parametrize("command", [
    [], ["init"], ["doctor"], ["project"], ["principal"], ["access"], ["client-config"], ["migrate"], ["serve"], ["mcp"], ["mcp-smoke"], ["admin"], ["admin", "seed"],
])
def test_help_requires_no_configuration(command, tmp_path, clean_environment):
    result = cli(*command, "--help", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "usage: contitext" in result.stdout
    assert not result.stderr


def test_version_matches_package(tmp_path, clean_environment):
    result = cli("--version", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == __version__


@pytest.mark.parametrize("args", [
    ["use", "demo"], ["!!", "contitext", "status"], ["admin", "delete"],
    ["serve", "--port", "not-a-port"], ["mcp", "--unknown"],
])
def test_invalid_commands_fail_before_starting_services(args, tmp_path, clean_environment):
    result = cli(*args, cwd=tmp_path)
    assert result.returncode == 2
    assert "error:" in result.stderr
    assert "Traceback" not in result.stderr


def test_migrate_and_admin_seed_use_the_configured_database(
    migrated_database_url, monkeypatch, tmp_path,
):
    document = {
        "projects": [{"id": "cli-demo", "display_name": "CLI Demo", "status": "active"}],
        "principals": [{"id": "55555555-5555-4555-8555-555555555555", "name": "CLI Owner"}],
        "acls": [{"project_id": "cli-demo", "principal_id": "55555555-5555-4555-8555-555555555555", "role": "owner"}],
    }
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    monkeypatch.setenv("CONTITEXT_AUTH_TOKENS", TEST_AUTH)
    monkeypatch.setenv("CONTITEXT_SEED_JSON", json.dumps(document))
    migrated = cli("migrate", cwd=tmp_path)
    assert migrated.returncode == 0, migrated.stderr
    for _ in range(2):
        seeded = cli("admin", "seed", cwd=tmp_path)
        assert seeded.returncode == 0, seeded.stderr
        assert json.loads(seeded.stdout) == {"status": "ok", "projects": 1, "principals": 1, "acls": 1}
    engine = create_engine(migrated_database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM projects WHERE id='cli-demo'")).scalar_one() == 1
            assert connection.execute(text("SELECT role FROM project_acl WHERE project_id='cli-demo'")).scalar_one() == "owner"
            assert connection.execute(text("SELECT count(*) FROM scope_bindings")).scalar_one() == 0
    finally:
        engine.dispose()


def test_admin_errors_use_canonical_command_and_do_not_leak_seed(monkeypatch, tmp_path):
    monkeypatch.setenv("CONTITEXT_SEED_JSON", "private-invalid-seed")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CONTITEXT_TEST_DATABASE_URL", raising=False)
    result = cli("admin", "seed", cwd=tmp_path)
    assert result.returncode == 2
    assert "contitext admin: error:" in result.stderr
    assert "private-invalid-seed" not in result.stderr


@pytest.mark.parametrize("entry", ["canonical", "legacy"])
def test_serve_honors_port_and_preserves_ready_endpoint(
    entry, migrated_database_url, monkeypatch, tmp_path,
):
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    monkeypatch.setenv("CONTITEXT_AUTH_TOKENS", TEST_AUTH)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    args = [str(BIN_DIR / "contitext"), "serve"] if entry == "canonical" else [str(BIN_DIR / "contitext-api")]
    with (tmp_path / "server.log").open("w+") as log:
        process = subprocess.Popen(
            [*args, "--host", "127.0.0.1", "--port", str(port)], cwd=tmp_path,
            stdout=log, stderr=log,
        )
        try:
            deadline = time.monotonic() + 10
            ready = False
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    with urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=0.5) as response:
                        ready = response.status == 200
                    if ready:
                        break
                except (URLError, TimeoutError):
                    time.sleep(0.05)
            log.flush()
            log.seek(0)
            assert ready, log.read()
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

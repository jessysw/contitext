from pathlib import Path
import json
import os
import shutil
import subprocess
import sys

from contitext.cli import migrate


ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_uses_fresh_credentials_and_preserves_existing_config(tmp_path):
    (tmp_path / "scripts").mkdir()
    script = tmp_path / "scripts/bootstrap.py"
    shutil.copyfile(ROOT / "scripts/bootstrap.py", script)
    package = tmp_path / "src" / "contitext"
    package.mkdir(parents=True)
    for name in ("__init__.py", "onboarding.py"):
        shutil.copyfile(ROOT / "src" / "contitext" / name, package / name)
    run = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert run.returncode == 0
    config = tmp_path / ".env"
    first = config.read_bytes()
    assert config.stat().st_mode & 0o777 == 0o600
    values = dict(line.split("=", 1) for line in first.decode().splitlines() if line and not line.startswith("#"))
    token = values["CONTITEXT_MCP_TOKEN"].strip("'")
    store = json.loads(values["CONTITEXT_AUTH_TOKENS"].strip("'"))
    assert len(token) >= 32 and token in store
    assert token not in run.stdout and token not in run.stderr
    repeated = subprocess.run([sys.executable, str(script)], capture_output=True)
    assert repeated.returncode != 0
    assert config.read_bytes() == first


def test_migration_entry_point_works_away_from_checkout(test_database_url, postgres_available, monkeypatch, tmp_path):
    monkeypatch.setenv("CONTITEXT_TEST_DATABASE_URL", test_database_url)
    monkeypatch.chdir(tmp_path)
    migrate()
    from sqlalchemy import create_engine, text
    engine = create_engine(test_database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0001_foundation"
    finally:
        engine.dispose()

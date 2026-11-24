"""Generated Python paths survive a Homebrew upgrade without guessing a keg."""
import json
from pathlib import Path
import shlex
import shutil
import sys

import pytest

from contitext.runtime_paths import integration_python
from contitext.hook_config import install
from contitext.plugin_export import export
from test_hooks import configured


def keg(root, version):
    directory = root / "Cellar" / "contitext" / version
    executable = directory / "libexec" / "bin" / "python3.14"
    executable.parent.mkdir(parents=True)
    executable.write_text(version)
    (executable.parent / "python").symlink_to(executable.name)
    return directory, executable


def running(monkeypatch, directory, executable):
    monkeypatch.setattr(sys, "prefix", str(directory / "libexec"))
    monkeypatch.setattr(sys, "executable", str(executable))


def test_only_current_verified_formula_uses_stable_opt(tmp_path, monkeypatch):
    old, executable = keg(tmp_path, "1.0")
    running(monkeypatch, old, executable)
    assert integration_python() == str(executable)
    opt = tmp_path / "opt" / "contitext"
    opt.parent.mkdir()
    opt.symlink_to(old, target_is_directory=True)
    stable = integration_python()
    assert stable == str(opt / "libexec" / "bin" / "python")
    new, _ = keg(tmp_path, "1.1")
    opt.unlink()
    opt.symlink_to(new, target_is_directory=True)
    assert integration_python() == str(executable)  # Never select another keg.
    shutil.rmtree(old)
    assert Path(stable).read_text() == "1.1"


def test_regular_venv_and_broken_opt_are_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "venv"))
    monkeypatch.setattr(sys, "executable", str(tmp_path / "venv/bin/python"))
    assert integration_python() == sys.executable
    directory, executable = keg(tmp_path, "1.0")
    running(monkeypatch, directory, executable)
    opt = tmp_path / "opt" / "contitext"
    opt.parent.mkdir()
    opt.symlink_to(tmp_path / "missing")
    assert integration_python() == str(executable)


@pytest.mark.parametrize("client", ["codex", "claude", "copilot", "cursor", "gemini", "hermes", "openclaw", "opencode"])
def test_generated_commands_follow_new_keg_after_cleanup(tmp_path, monkeypatch, client):
    args = configured(tmp_path)
    args.client = client
    old, executable = keg(tmp_path / "brew with spaces", "1.0")
    opt = old.parent.parent.parent / "opt" / "contitext"
    opt.parent.mkdir()
    opt.symlink_to(old, target_is_directory=True)
    running(monkeypatch, old, executable)
    if client in ("hermes", "openclaw", "opencode"):
        args.output = tmp_path / "plugin"
        export(args)
        profile = json.loads((args.output / "bridge.json").read_text())
        commands = [profile["command"]]
        if client == "hermes":
            commands.append(profile["identity_command"])
    else:
        install(args)
        events = json.loads(args.config.read_text())["hooks"]
        commands = []
        for entries in events.values():
            for entry in entries:
                handlers = [entry] if client in ("copilot", "cursor") else entry["hooks"]
                commands.extend(shlex.split(h["command"]) for h in handlers)
    new, _ = keg(old.parent.parent.parent, "1.1")
    opt.unlink()
    opt.symlink_to(new, target_is_directory=True)
    shutil.rmtree(old)
    for command in commands:
        assert "/opt/contitext/" in command[0]
        assert Path(command[0]).read_text() == "1.1"
        assert command[1:3] == ["-I", "-m"]

"""Shared syntax fixtures and delivery checks, not authenticated host acceptance."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

import pytest

from contitext.chat_commands import COMMANDS, HELP, parse_chat_command
from contitext.plugin_export import export
from test_hooks import configured

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/chat-commands.json'
CASES = json.loads(FIXTURE.read_text())
TARGETS = {
    'codex': '.codex/AGENTS.md', 'claude': '.claude/CLAUDE.md',
    'copilot': '.copilot/copilot-instructions.md', 'cursor': '.cursor/skills/contitext/SKILL.md',
    'opencode': '.config/opencode/AGENTS.md', 'gemini': '.gemini/GEMINI.md',
    'hermes': '.hermes/skills/contitext/SKILL.md', 'openclaw': '.openclaw/skills/contitext/SKILL.md',
    'zed': '.config/zed/AGENTS.md',
}


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['id'])
def test_python_chat_contract(case):
    assert parse_chat_command(case['input']) == case['expected']


def test_shell_json_entry_preserves_the_shared_contract():
    # A shell transports JSON to the same parser. It never evaluates chat text.
    for case in CASES:
        result = subprocess.run(['/bin/sh', '-c', 'exec "$1" -I -m contitext.chat_commands',
                                 'chat-contract', sys.executable],
                                input=json.dumps(case['input']), text=True, capture_output=True, timeout=5)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == case['expected'], case['id']


@pytest.mark.parametrize('client', ['openclaw', 'opencode'])
def test_exported_javascript_reference_uses_same_fixtures(tmp_path, client):
    node = shutil.which('node')
    if not node:
        if os.environ.get('CI'): pytest.fail('Node.js is required in CI')
        pytest.skip('Node.js required for exported JavaScript parser contract')
    args = configured(tmp_path); args.client = client; args.output = tmp_path / 'export'
    export(args)
    script = tmp_path / 'contract.mjs'
    script.write_text("import assert from 'node:assert/strict';\n"
                      "import {readFileSync} from 'node:fs';\n"
                      f"import {{parseChatCommand}} from {json.dumps((args.output/'index.mjs').as_uri())};\n"
                      f"const cases=JSON.parse(readFileSync({json.dumps(str(FIXTURE))},'utf8'));\n"
                      "for(const c of cases) assert.deepEqual(parseChatCommand(c.input),c.expected,c.id);\n")
    result = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    # Importing/parsing does not run a bridge, establish identity or create state.
    assert not (args.output / 'identities').exists()


@pytest.mark.parametrize('target', TARGETS)
def test_shell_installer_delivers_identical_protocol_for_each_agent(tmp_path, target):
    home = tmp_path / 'home'; home.mkdir()
    connection = tmp_path / 'client.json'
    connection.write_text(json.dumps({'command': '/bin/true'}))
    argv = ['/bin/sh', str(ROOT/'scripts/install-agent-adapters.sh'), '--home', str(home),
            '--config', str(connection), '--yaml-python', sys.executable, '--target', target]
    env = {**os.environ, 'CONTITEXT_INSTALL_PYTHON': sys.executable}
    result = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=10)
    assert result.returncode == 0, result.stderr
    content = (home / TARGETS[target]).read_text()
    protocol = (ROOT/'integrations/PROJECT-CONTEXT-PROTOCOL.md').read_text()
    assert protocol.strip() in content
    assert HELP in ' '.join(content.split()).replace('`', '')
    assert all(f'contitext: {command}' in content for command in COMMANDS if command != 'help')
    assert '!!' not in content and '！！' not in content and 'ctx:' not in content
    assert 'reference parsers' in content and 'not a universal native chat interceptor' in content
    # A server upgrade alone cannot replace a client's cached legacy protocol.
    # Reinstalling must replace the managed block without losing its wrapper.
    legacy = 'Use `!! contitext status`. Accept `!! ctx` and `！！ context` aliases.'
    (home / TARGETS[target]).write_text(content.replace(protocol.strip(), legacy))
    upgraded = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=10)
    assert upgraded.returncode == 0, upgraded.stderr
    assert (home / TARGETS[target]).read_text() == content
    # Replacement is idempotent and no shorthand executable is introduced.
    again = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=10)
    assert again.returncode == 0 and json.loads(again.stdout)['changed'] == []
    assert not (home/'.local/bin/ctx').exists()


def test_current_docs_and_executables_do_not_reintroduce_aliases():
    exceptions = {'upgrading-to-0.8.3.md', 'chat-commands.md', 'acceptance-0.8.3.md'}
    for path in [ROOT/'README.md', ROOT/'CONTRIBUTING.md', *sorted((ROOT/'docs').glob('*.md'))]:
        if path.name in exceptions:
            continue  # Explain the intentional breaking change and negative cases.
        assert '!!' not in path.read_text() and '！！' not in path.read_text(), path
    scripts = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['scripts']
    assert 'contitext' in scripts and 'ctx' not in scripts

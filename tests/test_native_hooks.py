"""Documented native payloads exercised through installed commands and real MCP."""
import asyncio
import json
from pathlib import Path
import shlex
import subprocess

import pytest

from contitext.hook_config import install
from contitext.hook_contracts import normalize, output
from contitext.hooks import identity
from contitext.hook_transport import hook_connection
from contitext.session_client import call
from test_hooks import configured
from test_cli import cli, BIN_DIR


def events(client, cwd):
    if client == 'copilot':
        return ('sessionStart', {'sessionId': 'native-chat', 'cwd': str(cwd), 'source': 'new'},
                'agentStop', {'sessionId': 'native-chat', 'cwd': str(cwd), 'transcriptPath': '/never/read'})
    if client == 'cursor':
        base = {'conversation_id': 'native-chat', 'workspace_roots': [str(cwd)]}
        return ('sessionStart', {**base, 'session_id': 'runtime-session', 'hook_event_name': 'sessionStart'},
                'afterAgentResponse', {**base, 'generation_id': 'turn-1', 'text': 'Completed native test.',
                                       'hook_event_name': 'afterAgentResponse'})
    return ('SessionStart', {'session_id': 'native-chat', 'cwd': str(cwd), 'source': 'resume', 'hook_event_name': 'SessionStart'},
            'AfterAgent', {'session_id': 'native-chat', 'cwd': str(cwd), 'prompt_response': 'Completed native test.',
                           'prompt': 'Never store the user prompt', 'hook_event_name': 'AfterAgent'})


def native_command(config, name):
    entry = config['hooks'][name][0]
    return entry.get('hooks', [entry])[0]['command']


def run_native(config, name, payload):
    result = subprocess.run(shlex.split(native_command(config, name)), input=json.dumps(payload),
                            capture_output=True, text=True, timeout=7)
    assert result.returncode == 0 and not result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('client', ['copilot', 'cursor', 'gemini'])
def test_native_configuration_preserves_settings_and_units(tmp_path, client):
    args = configured(tmp_path); args.client = client; args.checkpoints = True
    args.state_dir = tmp_path/'private'
    args.config.write_text(json.dumps({'permissions': {'deny': ['shell']}, 'hooks': {}}))
    result = install(args)
    config = json.loads(args.config.read_text())
    assert config['permissions'] == {'deny': ['shell']}
    assert not install(args)['changed']
    assert Path(result['backup']).exists()
    first, start, final, stop = events(client, tmp_path)
    handler = config['hooks'][first][0]
    if client == 'gemini':
        assert handler['hooks'][0]['timeout'] == 5000 and 'matcher' not in handler
    else:
        assert config['version'] == 1
        assert handler['timeoutSec' if client == 'copilot' else 'timeout'] == 5
    assert run_native(config, first, start) == {}  # Offline is advisory, never a veto.
    assert run_native(config, final, stop) == {}


def test_native_identity_rejects_conflicts_and_does_not_capture_transcripts():
    with pytest.raises(ValueError):
        normalize('copilot', {'sessionId':'one','session_id':'two'}, 'sessionStart')
    with pytest.raises(ValueError):
        normalize('gemini', {'hook_event_name':'AfterAgent'}, 'SessionStart')
    with pytest.raises(ValueError):
        normalize('cursor', {'hook_event_name':'subagentStop'})
    event = normalize('cursor', {'hook_event_name':'sessionStart','session_id':'runtime',
                                'conversation_id':'conversation','workspace_roots':['/one','/two']})
    assert event['cwd'] is None  # No arbitrary first workspace in multi-root sessions.
    assert identity('cursor', event) == ('cursor:conversation', 'runtime')
    event.pop('conversation_id')
    with pytest.raises(ValueError): identity('cursor', event)
    event = normalize('copilot', {'sessionId':'one','transcriptPath':'/private/chat',
                                 'last_assistant_message':'not in native contract'}, 'agentStop')
    assert 'last_assistant_message' not in event and 'transcriptPath' not in event
    for client in ('copilot','cursor','gemini'):
        result = output(client, {'hookSpecificOutput': {'additionalContext': 'project data'}})
        assert not set(result) & {'decision','continue','followup_message','permission'}


@pytest.mark.parametrize('client', ['copilot', 'cursor', 'gemini'])
def test_native_start_capture_and_manual_binding_real_mcp(migrated_database_url, monkeypatch, tmp_path, client):
    monkeypatch.setenv('DATABASE_URL', migrated_database_url)
    server = tmp_path/'server.env'
    assert cli('init','--project','demo','--output',str(server),cwd=tmp_path).returncode == 0
    assert cli('--env-file',str(server),'admin','seed','--if-empty',cwd=tmp_path).returncode == 0
    command = {'command': str(BIN_DIR/'contitext'), 'args': ['--env-file',str(server),'mcp']}
    args = configured(tmp_path, command); args.client = client; args.checkpoints = True
    args.state_dir = tmp_path/'private'
    install(args); config = json.loads(args.config.read_text())
    first, start, final, stop = events(client, tmp_path)
    result = run_native(config, first, start)
    text = (result.get('additionalContext') or result.get('additional_context')
            or result.get('hookSpecificOutput',{}).get('additionalContext'))
    assert f'{client}:native-chat' in text and '"project_id":"demo"' in text
    assert run_native(config, final, stop) == {}
    async def inspect_and_switch():
        async with hook_connection(command) as connection:
            context = await call(connection,'context_get',{'project_id':'demo','token_budget':8000})
            serialized = json.dumps(context)
            assert ('Completed native test.' in serialized) == (client != 'copilot')
            assert 'Never store the user prompt' not in serialized
            assert context['context']['checkpoint'] is None
            await call(connection,'project_create',{'project_id':'personal/other','display_name':'Other'})
            await call(connection,'project_bind',{'scope_id':f'{client}:native-chat',
                                                 'session_id':'manual','project_id':'personal/other'})
    asyncio.run(inspect_and_switch())
    resumed = run_native(config, first, start)
    assert '\\"project_id\\":\\"other\\"' in json.dumps(resumed)

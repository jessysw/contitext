"""Exported runtime modules, exact lineage and lifecycle contracts."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType

import pytest

from contitext.plugin_export import export
from contitext.plugin_identity import resolve
from contitext.resolution import ResolutionError
from test_hooks import configured
from test_cli import cli, BIN_DIR
from test_outbox import request


def exported(tmp_path, client):
    args = configured(tmp_path); args.client = client; args.output = tmp_path/'plugin'
    args.checkpoints = True; args.state_dir = tmp_path/'private'
    export(args)
    return args


@pytest.mark.parametrize('client', ['hermes', 'openclaw', 'opencode'])
def test_export_is_private_reviewable_and_never_enables_runtime(tmp_path, client):
    args = configured(tmp_path); args.client = client; args.output = tmp_path/'plugin'
    args.dry_run = True
    report = export(args)
    assert report['enabled'] is False and not args.output.exists()
    args.dry_run = False
    assert export(args)['enabled'] is False
    assert args.output.stat().st_mode & 0o777 == 0o700
    profile = json.loads((args.output/'bridge.json').read_text())
    assert profile['command'][:4] == [sys.executable, '-I', '-m', 'contitext.hooks']
    assert profile['checkpoints'] is False and '--state-dir' not in profile['command']
    for path in args.output.iterdir():
        assert not path.stat().st_mode & 0o077
    with pytest.raises(ResolutionError, match='destination must be new'): export(args)


def test_only_explicit_compression_preserves_lineage_across_restart(tmp_path):
    directory = tmp_path/'identities'; directory.mkdir(mode=0o700)
    assert resolve(directory, {'session_id':'original'}) == 'original'
    assert resolve(directory, {'session_id':'compressed','parent_session_id':'original',
                               'reason':'compression','reset':False}) == 'original'
    assert resolve(directory, {'session_id':'compressed'}) == 'original'  # Restart/resume.
    assert resolve(directory, {'session_id':'branch','parent_session_id':'original',
                               'reason':'branch','reset':False}) == 'branch'
    assert resolve(directory, {'session_id':'new','parent_session_id':'original',
                               'reason':'compression','reset':True}) == 'new'
    with pytest.raises((ValueError, OSError, ResolutionError)):
        resolve(directory, {'session_id':'missing','parent_session_id':'unknown',
                            'reason':'compression','reset':False})
    assert not any('project' in p.read_text() for p in directory.glob('*.identity.json'))


def test_hermes_provider_never_captures_user_or_subagent_and_drops_old_cwd(tmp_path, monkeypatch):
    args = exported(tmp_path, 'hermes')
    module = ModuleType('agent.memory_provider'); module.MemoryProvider = object
    monkeypatch.setitem(sys.modules, 'agent.memory_provider', module)
    spec = importlib.util.spec_from_file_location('exported_contitext_hermes', args.output/'__init__.py')
    plugin = importlib.util.module_from_spec(spec); spec.loader.exec_module(plugin)
    calls = []
    real_invoke = plugin.invoke
    def invoke(command, event):
        if 'contitext.plugin_identity' in command: return real_invoke(command, event)
        calls.append(event)
        return {'hookSpecificOutput': {'additionalContext': 'current project data'}}
    monkeypatch.setattr(plugin, 'invoke', invoke)
    provider = plugin.ContitextMemoryProvider()
    assert provider.is_available()
    provider.initialize('one', agent_context='primary', cwd=str(tmp_path))
    assert provider.prefetch('private question', session_id='one') == 'current project data'
    provider.sync_turn('private user input', 'assistant result', session_id='one')
    provider.on_pre_compress([{'role':'user','content':'private transcript'}])
    provider.on_session_switch('two',parent_session_id='one',reset=False,reason='compression')
    assert provider.prefetch('query',session_id='two')
    assert calls[-1]['conversation_id']=='one' and calls[-1]['session_id']=='two'
    provider.on_session_switch('branch',parent_session_id='two',reset=False,reason='branch')
    provider.prefetch('query',session_id='branch')
    assert calls[-1]['conversation_id']=='branch' and calls[-1]['cwd']==''
    before = len(calls)
    provider.prefetch('query', session_id='one')
    provider.initialize('child', agent_context='subagent',cwd=str(tmp_path))
    provider.sync_turn('private', 'subagent result', session_id='child')
    assert len(calls)==before
    assert not any(secret in json.dumps(calls) for secret in ('private question','private user input','private transcript'))
    restarted = plugin.ContitextMemoryProvider()
    restarted.initialize('two',agent_context='primary',cwd=str(tmp_path))
    assert restarted._root=='one'


@pytest.mark.parametrize('client', ['openclaw','opencode'])
def test_exported_javascript_lifecycle_and_isolation(tmp_path, client):
    node = shutil.which('node')
    if not node:
        if os.environ.get('CI'): pytest.fail('CI must install Node.js for native adapter tests')
        pytest.skip('Node.js required for native JavaScript adapter tests')
    args = exported(tmp_path, client)
    recorder = tmp_path/'recorder.py'
    recorder.write_text('import json,sys\nfrom pathlib import Path\ne=json.load(sys.stdin)\n'
        f'with Path({str(tmp_path/"events.jsonl")!r}).open("a") as f:f.write(json.dumps(e)+"\\n")\n'
        'print(json.dumps({"hookSpecificOutput":{"additionalContext":"scoped project data"}}))\n')
    profile = json.loads((args.output/'bridge.json').read_text()); profile['command']=[sys.executable,str(recorder)]
    (args.output/'bridge.json').write_text(json.dumps(profile))
    harness = tmp_path/'harness.mjs'
    common = "import assert from 'node:assert/strict';\n" + f"import plugin from {json.dumps((args.output/'index.mjs').as_uri())};\n"
    if client=='openclaw':
        code = """
const hooks={}; plugin.register({on:(name,fn)=>{hooks[name]=fn}});
const ctx={sessionId:'chat-one',workspaceDir:'/project'};
assert.deepEqual(await hooks.before_prompt_build({prompt:'private user',messages:['private history']},ctx),{prependContext:'scoped project data'});
assert.equal(await hooks.before_prompt_build({},{}),undefined);
await hooks.before_agent_finalize({sessionId:'chat-one',turnId:'turn-1',lastAssistantMessage:'assistant result'},ctx);
await hooks.before_agent_finalize({sessionId:'another',lastAssistantMessage:'wrong session'},ctx);
await hooks.before_compaction({},ctx);
await hooks.session_end({sessionId:'chat-one'},{sessionId:'chat-one'});
assert.deepEqual(Object.keys(hooks).sort(),['before_agent_finalize','before_compaction','before_prompt_build','session_end']);
assert.equal(await hooks.before_prompt_build({}, {...ctx,assertMemoryAudienceCurrent(){throw Error('changed')}}),undefined);
"""
    else:
        code = """
const hooks={};let disposed=0;
const ctx={location:{directory:'/project'},session:{
get:async({sessionID})=>({id:sessionID,location:{directory:sessionID==='other-location'?'/different':'/project'}}),
hook:async(name,fn)=>{hooks[name]=fn;return {dispose:async()=>disposed++}}},
event:{subscribe:async function*(){yield {type:'session.text.ended',id:'event-1',data:{sessionID:'chat-one',text:'assistant result'}};
yield {type:'session.execution.succeeded',data:{sessionID:'chat-one'}};}}};
const cleanup=await plugin.setup(ctx);
const event={sessionID:'chat-one',system:[],messages:['private history']};
await hooks.context(event);assert.equal(event.system[0].text,'scoped project data');
const other={sessionID:'other-location',system:[]};await hooks.context(other);assert.deepEqual(other.system,[]);
await hooks.compaction({sessionID:'chat-one'});
await new Promise(r=>setTimeout(r,300)); await cleanup(); assert.equal(disposed,2);
assert.deepEqual(Object.keys(hooks).sort(),['compaction','context']);
"""
    harness.write_text(common+code)
    result=subprocess.run([node,str(harness)],capture_output=True,text=True,timeout=12)
    assert result.returncode==0,result.stderr
    captured=(tmp_path/'events.jsonl').read_text()
    assert 'private' not in captured and 'wrong session' not in captured
    assert 'assistant result' in captured and 'other-location' not in captured


@pytest.mark.parametrize('client', ['hermes', 'openclaw', 'opencode'])
def test_exported_bridge_real_mcp_candidates_and_binding(migrated_database_url, monkeypatch, tmp_path, client):
    monkeypatch.setenv('DATABASE_URL', migrated_database_url)
    server=tmp_path/'server.env'
    assert cli('init','--project','demo','--output',str(server),cwd=tmp_path).returncode==0
    assert cli('--env-file',str(server),'admin','seed','--if-empty',cwd=tmp_path).returncode==0
    command={'command':str(BIN_DIR/'contitext'),'args':['--env-file',str(server),'mcp']}
    args=configured(tmp_path,command);args.client=client;args.output=tmp_path/'plugin'
    args.checkpoints=True;args.state_dir=tmp_path/'private'
    export(args)
    argv=json.loads((args.output/'bridge.json').read_text())['command']
    event={'hook_event_name':'SessionStart','session_id':'native-session','cwd':str(tmp_path)}
    if client=='hermes':event['conversation_id']='native-root'
    def send(payload):
        run=subprocess.run(argv,input=json.dumps(payload),capture_output=True,text=True,timeout=7)
        assert run.returncode==0 and not run.stderr
        return json.loads(run.stdout or '{}')
    assert f'{client}:native-' in send(event)['hookSpecificOutput']['additionalContext']
    send({**event,'hook_event_name':'Stop','last_assistant_message':'Native plugin candidate.'})
    result=request(command,'context_get',{'project_id':'demo','token_budget':8000})
    assert result['context']['checkpoint'] is None
    assert result['context']['progress_candidates'][0]['payload']['summary']=='Native plugin candidate.'
    scope=f'{client}:' + ('native-root' if client=='hermes' else 'native-session')
    request(command,'project_create',{'project_id':'personal/other','display_name':'Other'})
    request(command,'project_bind',{'project_id':'personal/other','scope_id':scope,'session_id':'manual'})
    # No cwd is needed to honor an existing explicit binding after a native switch.
    event.pop('cwd')
    assert '"project_id":"other"' in send(event)['hookSpecificOutput']['additionalContext']

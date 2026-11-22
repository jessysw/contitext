"""Write/read synthetic hook candidates in a disposable installed-package deployment.

Run with the installed wheel's Python, outside the source checkout. The explicitly
supplied connection/project MUST belong to a disposable acceptance deployment.
"""
import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from contitext.hook_transport import hook_connection
from contitext.resolution import load_connection
from contitext.session_client import call

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--connection',type=Path,required=True)
parser.add_argument('--project',required=True)
parser.add_argument('--directory',type=Path,required=True)
args=parser.parse_args()
args.directory.mkdir(mode=0o700)
cli=Path(sys.executable).parent/'contitext'
mappings=args.directory/'projects.json'
subprocess.run([cli,'mapping','add','--connection',args.connection,'--mappings',mappings,
                '--directory',args.directory,'--project',args.project],check=True,capture_output=True)


def invoke(command, value=None):
    result=subprocess.run(command,input=json.dumps(value) if value is not None else None,
                          capture_output=True,text=True,timeout=10)
    assert result.returncode==0 and not result.stderr, 'Installed client command failed'
    return json.loads(result.stdout or '{}')


async def verify(session):
    async with hook_connection(load_connection(args.connection)) as client:
        context=await call(client,'context_get',{'project_id':args.project,'token_budget':8000})
        matching=[e for e in context['context']['progress_candidates'] if session in e['payload']['summary']]
        assert len(matching)==1 and matching[0]['candidate'] is True
        assert context['used_budget']<=8000


for client in ('codex','claude','copilot','cursor','gemini','hermes','openclaw','opencode'):
    directory=args.directory/client;directory.mkdir(mode=0o700)
    state=directory/'state'
    session='acceptance-'+uuid4().hex
    common=['--client',client,'--connection',str(args.connection),'--mappings',str(mappings)]
    if client in ('hermes','openclaw','opencode'):
        exported=directory/'plugin'
        invoke([cli,'plugins','export',*common,'--output',str(exported),'--checkpoints','--state-dir',str(state)])
        command=json.loads((exported/'bridge.json').read_text())['command']
    else:
        config=directory/'hooks.json'
        invoke([cli,'hooks','install',*common,'--config',str(config),'--checkpoints','--state-dir',str(state)])
        hooks=json.loads(config.read_text())['hooks']
        entry=hooks['sessionStart' if client in ('copilot','cursor') else 'SessionStart'][0]
        import shlex
        command=shlex.split(entry['command'] if client in ('copilot','cursor') else entry['hooks'][0]['command'])
        report=invoke([cli,'hooks','doctor',*common,'--config',str(config),'--state-dir',str(state),'--timeout','7'])
        assert report['connection']=='ready' and report['runtime_activation']=='not_verified'
    event={'session_id':session,'cwd':str(args.directory),'hook_event_name':'SessionStart','source':'startup'}
    if client=='copilot':event={'sessionId':session,'cwd':str(args.directory),'source':'new'}
    if client=='cursor':event.update(hook_event_name='sessionStart',conversation_id=session)
    if client=='hermes':event['conversation_id']=session
    loaded=invoke(command,event)
    if client+':'+session not in json.dumps(loaded):
        diagnostic=invoke([cli,'hooks','status','--state-dir',str(state)])
        raise AssertionError(client+' startup did not load context: '+json.dumps(diagnostic.get('last_run')))
    checkpoint=[cli,'hooks','checkpoint',*common,'--state-dir',str(state),'--session-id',session,'--source-id','acceptance-turn']
    if client in ('cursor','hermes'):checkpoint+=['--conversation-id',session]
    for _ in range(2):
        result=subprocess.run(checkpoint,input='Installed artifact hook acceptance '+session,
                              capture_output=True,text=True,timeout=10)
        assert result.returncode==0 and not result.stderr
    assert not list(state.glob('*.pending.json'))
    asyncio.run(verify(session))
    if client not in ('hermes','openclaw','opencode'):
        assert invoke([cli,'hooks','disable','--client',client,'--config',str(config)])['changed']
        assert state.exists()
    print(client+': installed artifact startup, candidate write/read and idempotent retry passed')

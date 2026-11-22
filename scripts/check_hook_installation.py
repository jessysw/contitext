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
state=args.directory/'state';state.mkdir(mode=0o700)
cli=Path(sys.executable).parent/'contitext'
mappings=args.directory/'projects.json'
subprocess.run([cli,'mapping','add','--connection',args.connection,'--mappings',mappings,
                '--directory',args.directory,'--project',args.project],check=True,capture_output=True)
session='acceptance-'+uuid4().hex
event={'session_id':session,'cwd':str(args.directory),'hook_event_name':'SessionStart','source':'startup'}
command=[sys.executable,'-I','-m','contitext.hooks','--client','codex','--connection',str(args.connection),
         '--mappings',str(mappings),'--state-dir',str(state),'--timeout','3']
def hook(value):
    result=subprocess.run(command,input=json.dumps(value),capture_output=True,text=True,timeout=6)
    assert result.returncode==0 and not result.stderr
    return json.loads(result.stdout or '{}')
loaded=hook(event)
assert 'codex:'+session in loaded['hookSpecificOutput']['additionalContext']
stop={**event,'hook_event_name':'Stop','turn_id':'acceptance-turn','last_assistant_message':'Installed artifact hook acceptance '+session}
assert hook(stop)=={}
assert hook(stop)=={}
assert not list(state.glob('*.pending.json'))
async def verify():
    async with hook_connection(load_connection(args.connection)) as client:
        context=await call(client,'context_get',{'project_id':args.project,'token_budget':8000})
        matching=[e for e in context['context']['progress_candidates'] if session in e['payload']['summary']]
        assert len(matching)==1 and matching[0]['candidate'] is True
        assert context['used_budget']<=8000
asyncio.run(verify())
print('Installed-artifact session start, candidate checkpoint, idempotent retry and MCP read: passed')

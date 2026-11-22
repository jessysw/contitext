"""Durable candidate capture, exact-binding replay, failure and redaction."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import create_engine, text

from contitext.hook_config import install
from contitext.hook_transport import hook_connection
from contitext.outbox import redact, stage, status, remember
from contitext.repository import BindingConflictError
from contitext.schemas import BindProjectRequest
from contitext.session_client import call
from test_hooks import configured, invoke
from test_cli import cli, BIN_DIR
from test_assembly import setup, record


@pytest.fixture
def live(migrated_database_url, monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL',migrated_database_url)
    server=tmp_path/'server.env'
    assert cli('init','--project','demo','--output',str(server),cwd=tmp_path).returncode==0
    assert cli('--env-file',str(server),'admin','seed','--if-empty',cwd=tmp_path).returncode==0
    runner=tmp_path/'runner.py'
    code=f'import os\nos.execv({str(BIN_DIR/"contitext")!r},{[str(BIN_DIR/"contitext"),"--env-file",str(server),"mcp"]!r})\n'
    runner.write_text(code)
    command={'command':sys.executable,'args':[str(runner)]}
    args=configured(tmp_path,command); args.state_dir=tmp_path/'state';args.state_dir.mkdir(mode=0o700)
    args.task_id=None
    event={'hook_event_name':'SessionStart','session_id':'chat','cwd':str(tmp_path),'source':'startup'}
    assert invoke(args,event)[0]['hookSpecificOutput']
    yield args,event,command,runner,code


def request(command,name,args):
    async def run():
        async with hook_connection(command) as client:return await call(client,name,args)
    return asyncio.run(run())


def test_capture_redaction_idempotency_and_candidate_separation(live):
    args,event,command,_,_=live
    stop={**event,'hook_event_name':'Stop','turn_id':'turn-1',
          'last_assistant_message':'Implemented search. TOKEN=top-secret-value Bearer other-private-value'}
    assert invoke(args,stop)[0]=={}
    assert status(args.state_dir)['pending']==0
    invoke(args,stop)
    result=request(command,'context_get',{'project_id':'personal/demo','token_budget':8000})
    candidates=result['context']['progress_candidates']
    assert len(candidates)==1
    assert 'top-secret-value' not in json.dumps(candidates) and 'other-private-value' not in json.dumps(candidates)
    assert '[REDACTED]' in candidates[0]['payload']['summary']
    assert result['context']['checkpoint'] is None
    assert candidates[0]['candidate'] is True


def test_offline_capture_survives_worker_timeout_and_compaction_replays(live):
    args,event,command,runner,code=live
    runner.write_text('import time\ntime.sleep(30)\n');args.timeout=1
    stop={**event,'hook_event_name':'Stop','turn_id':'offline-1','last_assistant_message':'Prepared a regression test.'}
    assert invoke(args,stop)[0]=={}
    assert status(args.state_dir)['pending']==1
    pending=next(args.state_dir.glob('*.pending.json'))
    assert pending.stat().st_mode & 0o777==0o600
    runner.write_text(code);args.timeout=3
    # No last_assistant_message or transcript processing is needed for retry.
    assert invoke(args,{**event,'hook_event_name':'PreCompact','transcript_path':'/must/not/read'})[0]=={}
    assert status(args.state_dir)['pending']==0
    result=request(command,'context_get',{'project_id':'personal/demo','token_budget':8000})
    assert len(result['context']['progress_candidates'])==1


def test_switch_and_switch_back_never_retag_old_work(live):
    args,event,command,runner,code=live
    runner.write_text('import time\ntime.sleep(30)\n');args.timeout=1
    invoke(args,{**event,'hook_event_name':'Stop','last_assistant_message':'Old project progress'})
    runner.write_text(code);args.timeout=3
    request(command,'project_create',{'project_id':'personal/other','display_name':'Other'})
    request(command,'project_bind',{'project_id':'personal/other','scope_id':'codex:chat','session_id':'manual'})
    invoke(args,{**event,'hook_event_name':'SessionEnd'})
    assert status(args.state_dir)['pending']==1
    other=request(command,'context_get',{'project_id':'personal/other','token_budget':8000})
    assert other['context']['progress_candidates']==[]
    invoke(args,{**event,'hook_event_name':'Stop','last_assistant_message':'New project progress'})
    other=request(command,'context_get',{'project_id':'personal/other','token_budget':8000})
    assert other['context']['progress_candidates'][0]['payload']['summary']=='New project progress'
    request(command,'project_bind',{'project_id':'personal/demo','scope_id':'codex:chat','session_id':'manual-back'})
    invoke(args,{**event,'hook_event_name':'Interrupt'})
    assert status(args.state_dir)['pending']==1
    original=request(command,'context_get',{'project_id':'personal/demo','token_budget':8000})
    assert original['context']['progress_candidates']==[]


def test_server_timestamp_precondition_is_atomic(setup):
    service,writer,_,_=setup
    binding=service.current_project(writer,'scope:exact')
    saved, req=record(service,writer,'checkpoint')
    service.bind_project(writer,BindProjectRequest(project_id='alpha',scope_id='scope:exact',session_id='new'))
    req=req.model_copy(update={'expected_binding_updated_at':binding.updated_at})
    with pytest.raises(BindingConflictError,match='binding changed'):
        service.record_context(writer,req)


def test_secrets_are_redacted_before_truncation_and_storage():
    raw='password="some long value"\nhttps://user:secret@host/path\nghp_abcdefghijk\n-----BEGIN PRIVATE KEY-----\n'+'x'*5000+'\n-----END PRIVATE KEY-----'
    value=redact(raw)
    for private in ['some long value','user:secret','ghp_abcdefghijk','x'*10]:assert private not in value
    assert len(value.encode())<2450


def test_installer_is_opt_in_and_only_emits_supported_events(tmp_path):
    args=configured(tmp_path);args.checkpoints=True;args.state_dir=tmp_path/'state'
    result=install(args)
    hooks=json.loads(args.config.read_text())['hooks']
    assert set(hooks)=={'SessionStart','Stop','PreCompact','SessionEnd','Interrupt'}
    assert args.state_dir.stat().st_mode & 0o777==0o700
    assert not install(args)['changed']
    args.client='claude';args.config=tmp_path/'claude.json'
    install(args)
    assert 'Interrupt' not in json.loads(args.config.read_text())['hooks']
    assert all(h['timeout']==(3 if event in ('SessionEnd','Interrupt') else 4)
               for event,groups in hooks.items() for g in groups for h in g['hooks'])


def test_outbox_refuses_symlinks_and_capacity_without_overwriting(tmp_path):
    args=configured(tmp_path);args.state_dir=tmp_path/'state';args.state_dir.mkdir(mode=0o700)
    binding={'scope_id':'codex:chat','session_id':'chat','project_id':'personal/demo',
             'principal_id':'synthetic','updated_at':'time'}
    command=json.loads(args.connection.read_text());remember(args,command,binding)
    event={'session_id':'chat','hook_event_name':'Stop','last_assistant_message':'Candidate'}
    path=stage(args,event);assert stage(args,event)==path
    value=path.read_bytes();path.unlink();target=tmp_path/'preserve';target.write_bytes(value);path.symlink_to(target)
    with pytest.raises(ValueError):stage(args,event)
    assert target.read_bytes()==value
    path.unlink()
    for i in range(256):(args.state_dir/f'{i}.pending.json').write_text('{}')
    with pytest.raises(ValueError,match='capacity'):stage(args,event)


def test_explicit_cli_checkpoint_and_status(live,tmp_path):
    import subprocess
    args,event,command,_,_=live
    result=subprocess.run([str(BIN_DIR/'contitext'),'hooks','checkpoint','--client','codex',
        '--session-id','chat','--source-id','milestone-1','--connection',str(args.connection),
        '--mappings',str(args.mappings),'--state-dir',str(args.state_dir)],
        input='Implementation done; verification pending.',capture_output=True,text=True,timeout=10)
    assert result.returncode==0 and json.loads(result.stdout)['pending']==0
    report=cli('hooks','status','--state-dir',str(args.state_dir),cwd=tmp_path)
    assert report.returncode==0 and 'Implementation done' not in report.stdout
    context=request(command,'context_get',{'project_id':'personal/demo','token_budget':8000})
    assert context['context']['progress_candidates'][0]['payload']['hook_event']=='Checkpoint'

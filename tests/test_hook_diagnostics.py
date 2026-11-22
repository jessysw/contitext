import asyncio
import json
from pathlib import Path
import shlex
import sys

import pytest

from contitext.hook_config import disable, install
from contitext.hook_diagnostics import configured_events, doctor
from contitext.outbox import atomic_json, status
from test_hooks import configured, invoke


@pytest.mark.parametrize('client', ['codex','claude','copilot','cursor','gemini'])
def test_disable_removes_only_owned_commands_and_preserves_backup(tmp_path, client):
    args=configured(tmp_path);args.client=client;args.checkpoints=True;args.state_dir=tmp_path/'state'
    install(args)
    data=json.loads(args.config.read_text())
    name=next(iter(data['hooks']))
    if client in ('copilot','cursor'):
        data['hooks'][name].append({'type':'command','command':'echo contitext.hooks'})
    else:
        data['hooks'][name][0]['hooks'].append({'type':'command','command':'echo contitext.hooks'})
    data['permissions']={'deny':['shell']}
    args.config.write_text(json.dumps(data))
    args.dry_run=True
    assert disable(args)['changed'] and json.loads(args.config.read_text())==data
    args.dry_run=False
    result=disable(args)
    assert result['removed'] in (4,5) and json.loads(Path(result['backup']).read_text())==data
    remaining=json.loads(args.config.read_text())
    assert remaining['permissions']==data['permissions'] and 'echo contitext.hooks' in json.dumps(remaining)
    assert configured_events(remaining,client)=={}
    assert not disable(args)['changed'] and args.state_dir.exists()


def test_explicit_timeout_keeps_codex_end_deadline(tmp_path):
    args=configured(tmp_path);args.checkpoints=True;args.state_dir=tmp_path/'state';args.worker_timeout=7
    install(args)
    data=json.loads(args.config.read_text())
    for event, groups in data['hooks'].items():
        handler=groups[0]['hooks'][0]; argv=shlex.split(handler['command'])
        budget=float(argv[argv.index('--timeout')+1])
        assert budget==(2 if event in ('SessionEnd','Interrupt') else 7)
        assert handler['timeout']==budget+1


def test_local_diagnostic_explains_timeout_without_content(tmp_path):
    hang=tmp_path/'hang.py';hang.write_text('import time;time.sleep(60)')
    args=configured(tmp_path,{'command':sys.executable,'args':[str(hang)]})
    args.state_dir=tmp_path/'state';args.state_dir.mkdir(mode=0o700);args.timeout=0.2
    event={'hook_event_name':'SessionStart','session_id':'secret-session','cwd':str(tmp_path),
           'prompt':'private message TOKEN=not-for-logs'}
    result,elapsed=invoke(args,event)
    assert result=={} and elapsed<3
    report=status(args.state_dir)
    assert report['last_run']['outcome']=='timeout'
    for secret in ('secret-session','private message','not-for-logs',str(tmp_path)):
        assert secret not in json.dumps(report)
    diagnostic={**report['last_run'],'secret':'DO NOT PRINT'}
    atomic_json(args.state_dir/'last-run.json',diagnostic)
    assert 'DO NOT PRINT' not in json.dumps(status(args.state_dir))
    diagnostic['event']='TOKEN=DO NOT PRINT'
    atomic_json(args.state_dir/'last-run.json',diagnostic)
    assert status(args.state_dir)['last_run']=={'outcome':'invalid_diagnostic'}


def test_doctor_does_not_claim_runtime_activation_or_modify_configuration(tmp_path):
    args=configured(tmp_path);args.state_dir=None;args.timeout=0.5
    install(args)
    original=args.config.read_bytes()
    result=asyncio.run(doctor(args))
    assert result['configured_events']=={'SessionStart':1}
    assert result['runtime_activation']=='not_verified' and result['connection']=='unavailable'
    assert args.config.read_bytes()==original


def test_worker_failure_is_reported_without_blocking_parent(tmp_path):
    args=configured(tmp_path);args.state_dir=tmp_path/'state'
    args.state_dir.mkdir(mode=0o700)
    result,_=invoke(args,{'hook_event_name':'SessionStart','session_id':'offline','cwd':str(tmp_path)})
    assert result=={}
    assert status(args.state_dir)['last_run']['outcome']=='worker_error'

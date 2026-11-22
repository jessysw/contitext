import importlib.util,json,sys,tempfile,tomllib,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import install_agent_adapters as a
import pytest

def test_merge():
 w=Path('/tmp/safe path/wrapper')
 c='model = "keep"\n[mcp_servers.other]\ncommand="other"\n[mcp_servers.legacy]\ncommand="old"\nstartup_timeout_sec=60\n[mcp_servers.legacy.env]\nTOKEN="private"\n'
 result=a.codex_config(c,w,['legacy']); doc=tomllib.loads(result)
 assert doc['model']=='keep' and doc['mcp_servers']['other']['command']=='other'
 assert doc['mcp_servers']['contitext']==dict(command=str(w),args=[],startup_timeout_sec=60)
 assert a.codex_config(result,w,['legacy'])==result
 for parts in [['mcpServers'],['context_servers'],['mcp','servers']]:
  raw={'legacy':{'command':'old','toolFilter':{'include':['one','two']}},'other':{'command':'keep'}}
  for name in reversed(parts):raw={name:raw}
  text=json.dumps(raw).replace('["one", "two"]','["one", /*keep*/ "two",]')
  out=a.json_config(text,parts,w,['legacy']); node=a.node_value(out,a.parse_jsonc(out)[0])
  for p in parts:node=node[p]
  assert node['other']=={'command':'keep'} and node['contitext']['toolFilter']['include']==['one','two']
  assert a.json_config(out,parts,w,['legacy'])==out

def test_full_and_backup(tmp_path,capsys):
 cfg=tmp_path/'connection.json';cfg.write_text(json.dumps({'command':'/bin/echo','args':['literal $(false); `false`']}))
 home=tmp_path/'home';home.mkdir()
 (home/'.codex').mkdir(); (home/'.codex/config.toml').write_text('model="original"\n')
 argv=['--home',str(home),'--config',str(cfg),'--target','codex','--target','claude','--target','zed','--target','openclaw']
 a.main(argv+['--dry-run']);assert not (home/'.local').exists();capsys.readouterr()
 a.main(argv); first=json.loads(capsys.readouterr().out)
 assert (Path(first['backup'])/'.codex/config.toml').read_text()=='model="original"\n'
 assert subprocess.check_output([str(home/'.local/bin/contitext-mcp-codex')],text=True).strip()=='literal $(false); `false`'
 a.main(argv);assert json.loads(capsys.readouterr().out)['changed']==[]

def test_symlink_and_ambiguity(tmp_path):
 home=tmp_path/'home';home.mkdir();(home/'.codex').symlink_to(tmp_path,target_is_directory=True)
 with pytest.raises(a.InstallError):a.safe_path(home/'.codex/config.toml',home)
 with pytest.raises(a.InstallError):a.migrated_entry({'contitext':{},'legacy':{}},Path('/tmp/w'),['legacy'])
 with pytest.raises(a.InstallError):a.markdown(a.BEGIN,'protocol','codex',[])

def test_hermes():
 pytest.importorskip('yaml')
 py=sys.executable
 text='model:\n  name: keep\nmcp_servers:\n  legacy:\n    command: old\n  other:\n    command: keep\nlast: value\n'
 out=a.hermes_config(text,Path('/tmp/w'),['legacy'],py)
 parsed=a.yaml_document(out,py)
 assert parsed['model']=={'name':'keep'} and parsed['last']=='value'
 assert parsed['mcp_servers']['other']=={'command':'keep'}
 assert a.hermes_config(out,Path('/tmp/w'),['legacy'],py)==out


def test_concurrent_change_is_preserved(tmp_path, monkeypatch, capsys):
    home=tmp_path/'home'; (home/'.codex').mkdir(parents=True)
    codex=home/'.codex/config.toml';codex.write_text('model="before"\n')
    config=tmp_path/'client.json';config.write_text('{"command":"/bin/true"}')
    original=a.json_config
    def changed(*args,**kwargs):
        codex.write_text('model="concurrent"\n')
        return original(*args,**kwargs)
    monkeypatch.setattr(a,'json_config',changed)
    with pytest.raises(SystemExit):
        a.main(['--home',str(home),'--config',str(config),'--target','codex','--target','claude'])
    assert codex.read_text()=='model="concurrent"\n'
    assert not (home/'.local/bin/contitext-mcp-codex').exists()


def test_per_agent_launchers_preserve_other_client_and_old_shared_launcher(tmp_path, capsys):
    home=tmp_path/'home'; (home/'.local/bin').mkdir(parents=True)
    shared=home/'.local/bin/contitext-mcp-client'
    shared.write_text('#!/bin/sh\nexec /bin/echo old\n')
    (home/'.codex').mkdir()
    (home/'.codex/config.toml').write_text('[mcp_servers.contitext]\ncommand='+json.dumps(str(shared))+'\n')
    config=tmp_path/'client.json'
    config.write_text('{"command":"/bin/echo","args":["agent-a"]}')
    a.main(['--home',str(home),'--config',str(config),'--target','codex'])
    capsys.readouterr()
    first=(home/'.local/bin/contitext-mcp-codex').read_bytes()
    config.write_text('{"command":"/bin/echo","args":["agent-b"]}')
    a.main(['--home',str(home),'--config',str(config),'--target','claude'])
    result=json.loads(capsys.readouterr().out)
    assert set(result['launchers'])=={'claude'}
    assert (home/'.local/bin/contitext-mcp-codex').read_bytes()==first
    assert shared.read_text()=='#!/bin/sh\nexec /bin/echo old\n'
    for target, expected in [('codex','agent-a'),('claude','agent-b')]:
        assert subprocess.check_output([str(home/('.local/bin/contitext-mcp-'+target))],text=True).strip()==expected


def test_managed_skill_migration_is_repeatable(tmp_path, capsys):
    home=tmp_path/'home'; old=home/'.openclaw/skills/old-context/SKILL.md'
    old.parent.mkdir(parents=True)
    old.write_text('---\nname: old-context\n---\n\n# Old Context\n\n<!-- BEGIN OLD CONTEXT MANAGED BLOCK -->\nold protocol\n<!-- END OLD CONTEXT MANAGED BLOCK -->\n')
    config=tmp_path/'client.json';config.write_text('{"command":"/bin/true"}')
    args=['--home',str(home),'--config',str(config),'--target','openclaw','--replace-skill','old-context','--replace-marker','OLD CONTEXT']
    a.main(args); first=json.loads(capsys.readouterr().out)
    assert not old.exists()
    assert (Path(first['backup'])/old.relative_to(home)).is_file()
    new=home/'.openclaw/skills/contitext/SKILL.md'
    assert '# Contitext' in new.read_text() and '!! contitext' in new.read_text()
    a.main(args);assert json.loads(capsys.readouterr().out)['changed']==[]


def test_credentials_rejected_without_echo(tmp_path, capsys):
    home=tmp_path/'home'; home.mkdir()
    config=tmp_path/'client.json'; config.write_text('{"command":"/bin/true","env":{"SECRET":"do-not-echo-this"}}')
    with pytest.raises(SystemExit):
        a.main(['--home',str(home),'--config',str(config),'--target','codex'])
    assert 'do-not-echo-this' not in capsys.readouterr().err
    assert not (home/'.local').exists()


def test_complete_legacy_allowlist_expands_but_custom_restrictions_survive():
    original=['project_bind','project_current','context_get','context_search','context_record','context_handoff']
    wrapper=Path('/tmp/wrapper')
    entry,_=a.migrated_entry({'contitext':{'command':str(wrapper),'toolFilter':{'include':original}}},wrapper,[])
    assert entry['toolFilter']['include']==original+['project_list','project_create']
    restricted={'command':str(wrapper),'toolFilter':{'include':['context_get']},'enabled_tools':['context_get']}
    entry,_=a.migrated_entry({'contitext':restricted},wrapper,[])
    assert entry['toolFilter']['include']==['context_get'] and entry['enabled_tools']==['context_get']

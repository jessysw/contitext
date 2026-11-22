"""Deterministic local mappings and non-overwriting MCP resolution."""
import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace as NS

import pytest

from contitext.resolution import (
    ResolutionError, canonical_remote, connection_key, edit_mapping, load_connection,
    load_mappings, read_local_json, select_mapping,
)
from contitext.session_client import resolve_with_client


def mapping(kind, match, project='team/alpha'):
    return {'kind': kind, 'match': match, 'project': project}


def git(path, *args):
    return subprocess.run(['git', '-C', str(path), *args], check=True, capture_output=True)


@pytest.mark.parametrize('value', ['https://GITHUB.com/example/project.git', 'git@github.com:example/project.git', 'ssh://git@github.com/example/project', 'ssh://git@github.com:22/example/project', 'https://github.com:443/example/project'])
def test_remote_transport_equivalence(value):
    assert canonical_remote(value) == 'github.com/example/project'


@pytest.mark.parametrize('value', ['https://secret@example.com/owner/repo', 'https://user:private-token@example.com/owner/repo', 'git@host:../project', 'file:///private/repo', '/repo', 'https://host/owner/repo?token=secret', 'https://host/owner/repo#other', 'https://host/owner/%72epo', 'ssh://operator@host/owner/repo', 'https://host/owner//repo', 'https://host/repo', 'http://host/owner/repo'])
def test_remote_rejects_ambiguous_or_secret_spellings(value):
    with pytest.raises(ResolutionError) as error:
        canonical_remote(value)
    assert 'private-token' not in str(error.value)


def test_endpoint_and_full_path_are_part_of_identity():
    assert canonical_remote('ssh://git@host:2222/a/repo') != canonical_remote('https://host/a/repo')
    assert canonical_remote('https://host/a/repo') != canonical_remote('https://host/b/repo')
    assert canonical_remote('https://host/A/repo') != canonical_remote('https://host/a/repo')


def test_unique_remote_precedence_ambiguity_and_no_basename_guess(tmp_path, monkeypatch):
    repo = tmp_path / 'alpha'; repo.mkdir(); git(repo, 'init')
    git(repo, 'remote', 'add', 'origin', 'git@github.com:example/alpha.git')
    entries = [mapping('remote', 'github.com/example/alpha'), mapping('directory', str(repo), 'other/alpha')]
    assert select_mapping({'mappings': entries}, repo).project == 'team/alpha'
    git(repo, 'remote', 'add', 'upstream', 'https://github.com/upstream/alpha.git')
    entries.append(mapping('remote', 'github.com/upstream/alpha', 'upstream/alpha'))
    assert select_mapping({'mappings': entries}, repo).status == 'ambiguous'
    entries[-1]['project'] = 'team/alpha'
    assert select_mapping({'mappings': entries}, repo).project == 'team/alpha'
    entries = [mapping('remote', 'github.com/unrelated/alpha')]
    assert select_mapping({'mappings': entries}, repo).status == 'unmatched'
    other = tmp_path / 'other'; other.mkdir(); git(other, 'init')
    git(other, 'remote', 'add', 'origin', 'https://github.com/unrelated/alpha')
    monkeypatch.setenv('GIT_DIR', str(other / '.git'))
    monkeypatch.setenv('GIT_WORK_TREE', str(other))
    assert select_mapping({'mappings': entries}, repo).status == 'unmatched'


def test_directory_specificity_boundaries_and_symlinks(tmp_path):
    repo = tmp_path / 'repo'; repo.mkdir(); sub = repo / 'sub'; sub.mkdir()
    sibling = tmp_path / 'repo-other'; sibling.mkdir()
    link = tmp_path / 'alias'; link.symlink_to(sub)
    data = {'mappings': [mapping('directory', str(repo)), mapping('directory', str(sub), 'team/sub')]}
    assert select_mapping(data, link).project == 'team/sub'
    assert select_mapping(data, sibling).status == 'unmatched'


def options(tmp_path, **overrides):
    config = tmp_path / 'client.json'
    if not config.exists():
        config.write_text(json.dumps({'command': '/usr/bin/true', 'args': []}))
    return argparse.Namespace(mapping_action='add', connection=config, mappings=tmp_path/'projects.json',
                              remote='https://github.com/example/repo.git', directory=None,
                              project='team/project', **overrides)


def test_operator_mapping_edits_are_explicit_private_and_connection_scoped(tmp_path):
    args = options(tmp_path)
    assert edit_mapping(args)['mapping_count'] == 1
    assert args.mappings.stat().st_mode & 0o777 == 0o600
    before = args.mappings.read_bytes()
    assert edit_mapping(args)['mapping_count'] == 1
    args.project = 'other/project'
    with pytest.raises(ResolutionError, match='already maps'):
        edit_mapping(args)
    assert args.mappings.read_bytes() == before
    connection = load_connection(args.connection)
    with pytest.raises(ResolutionError, match='different MCP connection'):
        load_mappings(args.mappings, {'command': '/another/server', 'args': []})
    args.mapping_action = 'list'
    assert edit_mapping(args)['mappings'][0]['project'] == 'team/project'
    args.mapping_action = 'remove'
    assert edit_mapping(args)['mapping_count'] == 0
    args.mapping_action = 'add'; args.project = 'project'
    with pytest.raises(ResolutionError, match='workspace/project'):
        edit_mapping(args)


def test_remove_mapping_after_directory_move(tmp_path):
    args = options(tmp_path); repo = tmp_path / 'repo'; repo.mkdir()
    args.remote = None; args.directory = repo
    edit_mapping(args); repo.rename(tmp_path / 'moved')
    args.mapping_action = 'remove'
    assert edit_mapping(args)['mapping_count'] == 0


def test_trust_permissions_duplicates_and_symlinks(tmp_path):
    args = options(tmp_path); edit_mapping(args)
    args.mappings.chmod(0o644)
    with pytest.raises(ResolutionError, match='permissions'):
        load_mappings(args.mappings, load_connection(args.connection))
    args.mappings.chmod(0o600)
    link = tmp_path/'link.json'; link.symlink_to(args.mappings)
    with pytest.raises(ResolutionError):read_local_json(link, private=True)
    args.mappings.write_text('{"version": 1, "version": 2}')
    with pytest.raises(ResolutionError, match='duplicate JSON'):
        read_local_json(args.mappings, private=True)
    data = {'version': 1, 'connection': connection_key(load_connection(args.connection)),
            'mappings': [mapping('remote','github.com/example/repo')]*2}
    args.mappings.write_text(json.dumps(data))
    with pytest.raises(ResolutionError, match='duplicate mapping'):
        load_mappings(args.mappings, load_connection(args.connection))
    args.connection.write_text('{"command":"/bin/true","env":{"TOKEN":"private-token"}}')
    with pytest.raises(ResolutionError, match='command/args'):
        load_connection(args.connection)


class FakeClient:
    def __init__(self, *, current=None, atomic=True, denied=False, concurrent=None):
        self.current, self.atomic, self.denied, self.concurrent = current, atomic, denied, concurrent
        self.calls = []
    async def list_tools(self):
        return NS(tools=[NS(name='project_bind', inputSchema={'properties': {'if_unbound': {}} if self.atomic else {}})])
    async def call_tool(self, name, args):
        self.calls.append((name,args))
        if name=='project_current':
            if self.current:return NS(isError=False, structuredContent=self.current)
            return NS(isError=True, content=[NS(text='Error executing tool project_current: scope is not bound')])
        if self.denied:return NS(isError=True, content=[NS(text='project not found')])
        if name=='project_bind':return NS(isError=False, structuredContent=self.concurrent or {'project_id':args['project_id']})
        return NS(isError=False, structuredContent={})


def test_binding_precedence_and_old_server_no_blind_write(tmp_path):
    async def run():
        current={'project_id':'manual/project'}
        def invalid_mappings():raise AssertionError('existing binding must bypass mapping discovery')
        c=FakeClient(current=current)
        result=await resolve_with_client(c,invalid_mappings,tmp_path,'scope','session',bind=True)
        assert result['source']=='binding' and result['project_id']=='manual/project'
        assert len(c.calls)==1
        maps={'mappings':[mapping('directory',str(tmp_path))]}
        c=FakeClient(atomic=False)
        with pytest.raises(ResolutionError,match='lacks atomic'):
            await resolve_with_client(c,maps,tmp_path,'scope','session',bind=True)
        assert not any(name=='project_bind' for name,_ in c.calls)
        c=FakeClient(concurrent=current)
        result=await resolve_with_client(c,maps,tmp_path,'scope','session',bind=True)
        assert result['project_id']=='manual/project'
        assert c.calls[-1][1]['if_unbound'] is True
        c=FakeClient(denied=True)
        with pytest.raises(ResolutionError):
            await resolve_with_client(c,maps,tmp_path,'scope','session',bind=False)
        assert not any(name=='project_bind' for name,_ in c.calls)
    asyncio.run(run())


def test_cli_preview_help_and_invalid_timeout_do_not_require_database():
    result=subprocess.run([sys.executable,'-m','contitext.cli','resolve','--help'],capture_output=True,text=True)
    assert result.returncode==0 and '--bind' in result.stdout
    result=subprocess.run([sys.executable,'-m','contitext.cli','mapping','add','--mappings','/missing','--connection','/missing','--remote','https://host/a/b','--project','team/project'],capture_output=True,text=True)
    assert result.returncode==2 and 'cannot read trusted' in result.stderr


def test_real_stdio_preview_bind_and_manual_override(migrated_database_url, monkeypatch, tmp_path):
    from contitext.diagnostics import client_config
    from contitext.session_client import connect, call, UnboundScope
    from test_cli import cli, BIN_DIR
    monkeypatch.setenv('DATABASE_URL', migrated_database_url)
    config = tmp_path / 'server.env'
    assert cli('init', '--project', 'alpha', '--output', str(config), cwd=tmp_path).returncode == 0
    assert cli('--env-file', str(config), 'admin', 'seed', '--if-empty', cwd=tmp_path).returncode == 0
    connection = client_config(NS(compose=None, config_file=str(config), executable=str(BIN_DIR/'contitext'),
                                  ssh=None, credential_file=None))['mcpServers']['contitext']
    config_json = tmp_path/'client.json'; config_json.write_text(json.dumps(connection))
    options = NS(mapping_action='add', connection=config_json, mappings=tmp_path/'projects.json',
                 remote=None, directory=tmp_path, project='personal/alpha')
    edit_mapping(options)
    maps = load_mappings(options.mappings, connection)

    async def run():
        async with connect(connection) as client:
            result = await resolve_with_client(client, maps, tmp_path, 'new-chat', 'first', bind=False)
            assert result['status'] == 'matched'
            with pytest.raises(UnboundScope):
                await call(client, 'project_current', {'scope_id':'new-chat'})
            bound = await resolve_with_client(client, maps, tmp_path, 'new-chat', 'first', bind=True)
            assert bound['status'] == 'bound' and bound['project_id'] == 'alpha'
            await call(client, 'project_create', {'project_id':'personal/beta', 'display_name':'Beta'})
            await call(client, 'project_bind', {'project_id':'personal/beta', 'scope_id':'new-chat', 'session_id':'manual'})
        async with connect(connection) as client:
            result = await resolve_with_client(client, maps, tmp_path, 'new-chat', 'restart', bind=True)
            assert result['project_id'] == 'beta'
            assert result['binding']['session_id'] == 'manual'
    asyncio.run(run())

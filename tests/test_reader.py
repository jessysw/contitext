"""Human-readable exports preserve access boundaries and never change context state."""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from contitext.auth import ProjectNotFoundError
from contitext.projector import ProjectionSafetyError
from contitext.reader import ReaderDirectory, project_filename, render, run, snapshot
from contitext.schemas import BindProjectRequest, CreateProjectRequest, RecordContextRequest
from test_cli import cli
from test_projects import setup


def record(service, caller, project, message, kind="checkpoint"):
    scope = "reader-test:" + project
    service.bind_project(caller, BindProjectRequest(project_id=project, scope_id=scope, session_id="reader-test"))
    service.record_context(caller, RecordContextRequest(
        project_id=project, scope_id=scope, session_id="reader-test", agent_id="agent-a",
        source_kind="test", source_id=message, event_kind=kind, payload={"summary": message},
        idempotency_key=message,
    ))


def configured(monkeypatch, url, identity):
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("CONTITEXT_AUTH_TOKENS", json.dumps({"reader-test-only": {"principal_id": str(identity.principal_id), "name": identity.name}}))
    monkeypatch.setenv("CONTITEXT_MCP_TOKEN", "reader-test-only")
    monkeypatch.delenv("CONTITEXT_WRITER_FENCE_FILE", raising=False)


def database_state(engine):
    with engine.connect() as c:
        names = c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars().all()
        return {name: c.execute(text("SELECT coalesce(jsonb_agg(to_jsonb(t)),'[]') FROM " + name + " t")).scalar_one() for name in names}


def test_reader_exports_only_accessible_data_without_mutation(migrated_database_url, tmp_path):
    engine, caller, other, service = setup(migrated_database_url)
    try:
        for identity, project in [(caller, "visible"), (other, "hidden")]:
            service.create_project(identity, CreateProjectRequest(project_id=project, display_name=project.title()))
            record(service, identity, project, project + " checkpoint")
        with engine.begin() as c:
            c.execute(text("UPDATE project_acl SET role='reader' WHERE project_id=(SELECT id FROM projects WHERE workspace_id='00000000-0000-4000-8000-000000000001' AND slug='visible')"))
        before = database_state(engine)
        data = snapshot(engine, caller)
        assert [p['id'] for p in data] == ['visible'] and data[0]['role'] == 'reader'
        folder = ReaderDirectory(tmp_path / 'vault', str(caller.principal_id))
        try:
            result = folder.publish(data)
            assert result['projects'] == result['events'] == 1
            contents = ''.join(p.read_text() for p in folder.path.glob('*.md'))
            assert 'visible checkpoint' in contents and 'hidden' not in contents
            assert 'Latest checkpoint' in contents
            with pytest.raises(ProjectNotFoundError):
                snapshot(engine, caller, ['hidden'])
            assert database_state(engine) == before
        finally:
            folder.close()
    finally:
        engine.dispose()


def test_refresh_discovers_new_projects_and_removes_revoked_generated_files(migrated_database_url, tmp_path):
    engine, caller, other, service = setup(migrated_database_url)
    folder = ReaderDirectory(tmp_path / 'vault', str(caller.principal_id))
    try:
        service.create_project(caller, CreateProjectRequest(project_id='first', display_name='First'))
        folder.publish(snapshot(engine, caller))
        old = folder.path / project_filename('first')
        assert old.is_file()
        settings = folder.path / '.obsidian'; settings.mkdir(); (settings / 'app.json').write_text('{}')
        service.create_project(caller, CreateProjectRequest(project_id='second', display_name='Second'))
        record(service, caller, 'second', 'Ready for review')
        with engine.begin() as c:
            c.execute(text("DELETE FROM project_acl WHERE project_id=(SELECT id FROM projects WHERE workspace_id='00000000-0000-4000-8000-000000000001' AND slug='first')"))
        folder.publish(snapshot(engine, caller))
        assert not old.exists()
        assert (folder.path / project_filename('second')).is_file()
        assert (settings / 'app.json').read_text() == '{}'
        assert 'Ready for review' in (folder.path / project_filename('second')).read_text()
    finally:
        folder.close(); engine.dispose()


def test_output_safety_ownership_and_interrupted_refresh(tmp_path, monkeypatch):
    arbitrary = tmp_path / 'notes'; arbitrary.mkdir(); (arbitrary / 'personal.md').write_text('keep')
    with pytest.raises(ValueError, match='empty'):
        ReaderDirectory(arbitrary, 'owner')
    link = tmp_path / 'link'; link.symlink_to(arbitrary, target_is_directory=True)
    with pytest.raises(ProjectionSafetyError):
        ReaderDirectory(link, 'owner')
    root = tmp_path / 'vault'; folder = ReaderDirectory(root, 'owner')
    try:
        with pytest.raises(ValueError, match='another exporter'):
            ReaderDirectory(root, 'owner')
        external = tmp_path / 'external.md'; external.write_text('untouched')
        (root / 'README.md').symlink_to(external)
        with pytest.raises(ProjectionSafetyError):
            folder.publish([])
        assert external.read_text() == 'untouched'
        (root / 'README.md').unlink()
        data = [{'id': 'new', 'name': 'New', 'role': 'owner', 'status': 'active', 'events': []}]
        original = folder.write
        def fail(name, content):
            if name == 'README.md': raise OSError('interrupted refresh')
            original(name, content)
        monkeypatch.setattr(folder, 'write', fail)
        with pytest.raises(OSError): folder.publish(data)
        assert (root / project_filename('new')).exists()
    finally:
        folder.close()
    with pytest.raises(ValueError, match='identity'):
        ReaderDirectory(root, 'other')
    resumed = ReaderDirectory(root, 'owner')
    try:
        resumed.publish([])
        assert not (root / project_filename('new')).exists()
        assert not resumed.manifest['pending']
    finally:
        resumed.close()
    assert (arbitrary / 'personal.md').read_text() == 'keep'


def test_markdown_is_readable_without_active_stored_embeds():
    event = {'id': 'event-id', 'kind': 'handoff', 'created_at': '2026-01-01T00:00:00+00:00',
             'payload': {'summary': 'Continue the project', 'next_action': 'Implement endpoint',
                         'completed': ['Design'], 'blockers': [], 'unsafe': '<script>x</script> ![x](https://example.test) [[embed]]'},
             'agent_id': 'Agent A', 'source_kind': 'test', 'source_id': 'source'}
    projects = [{'id': p, 'name': 'Project', 'role': 'owner', 'status': 'active', 'events': [event]} for p in ['Demo', 'demo']]
    pages = render(projects, '2026-01-01T00:00:00+00:00')
    assert project_filename('Demo') != project_filename('demo')
    page = pages[project_filename('Demo')]
    assert '**Next action:** Implement endpoint' in page and '- Design' in page
    assert '<script>' not in page and '![x]' not in page and '[[embed]]' not in page
    assert '```json' not in page


def test_cli_export_uses_installed_package_and_reports_failure(migrated_database_url, tmp_path, monkeypatch):
    engine, caller, _, service = setup(migrated_database_url)
    try:
        service.create_project(caller, CreateProjectRequest(project_id='cli-reader', display_name='CLI Reader'))
        record(service, caller, 'cli-reader', 'CLI content')
        configured(monkeypatch, migrated_database_url, caller)
        output = tmp_path / 'vault'
        before = database_state(engine)
        result = cli('export', '--output', str(output), cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['events'] == 1
        assert database_state(engine) == before
        bad = cli('export', '--output', str(output), '--watch', '1', cwd=tmp_path)
        assert bad.returncode == 2
        monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://private-user:private-password@127.0.0.1:1/private-db?connect_timeout=1')
        failed = cli('export', '--output', str(output), cwd=tmp_path)
        assert failed.returncode == 1
        assert 'private-password' not in failed.stdout + failed.stderr
        assert 'Refresh failed' in (output / 'SYNC-STATUS.md').read_text()
        assert 'CLI content' in (output / project_filename('cli-reader')).read_text()
    finally:
        engine.dispose()


def test_watcher_recovers_and_refreshes_without_writing_events(migrated_database_url, tmp_path, monkeypatch):
    import contitext.reader as reader
    engine, caller, _, service = setup(migrated_database_url)
    try:
        service.create_project(caller, CreateProjectRequest(project_id='watch', display_name='Watch'))
        configured(monkeypatch, migrated_database_url, caller)
        fence = tmp_path / 'fence'; fence.write_text('maintenance')
        monkeypatch.setenv('CONTITEXT_WRITER_FENCE_FILE', str(fence))
        sleeps = []
        def advance(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 1:
                assert 'Refresh failed' in (tmp_path / 'vault/SYNC-STATUS.md').read_text()
                fence.unlink()
                record(service, caller, 'watch', 'New event after the first attempt')
            else:
                raise KeyboardInterrupt
        monkeypatch.setattr(reader.time, 'sleep', advance)
        assert run(SimpleNamespace(output=tmp_path / 'vault', project=None, watch=10)) == 0
        page = (tmp_path / 'vault' / project_filename('watch')).read_text()
        assert 'New event after the first attempt' in page
        assert 'Status: **OK**' in (tmp_path / 'vault/SYNC-STATUS.md').read_text()
        with engine.connect() as c:
            assert c.execute(text('SELECT count(*) FROM context_events')).scalar_one() == 1
            assert c.execute(text('SELECT count(*) FROM projection_offsets')).scalar_one() == 0
    finally:
        engine.dispose()

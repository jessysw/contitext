#!/usr/bin/env python3
"""Validate built archives before publishing; never print archive contents."""
import argparse
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
import tarfile
import tomllib
import zipfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('directory', type=Path)
a = p.parse_args()
version = tomllib.loads((Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text())['project']['version']
root = Path(__file__).resolve().parents[1]
expected = {f'contitext-{version}.tar.gz', f'contitext-{version}-py3-none-any.whl'}
archives = {x.name: x for x in a.directory.iterdir() if x.is_file()}
assert set(archives) == expected, 'expected exactly one matching sdist and wheel'
for name, path in archives.items():
    if name.endswith('.whl'):
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            metadata_name, = [x for x in names if x.endswith('.dist-info/METADATA')]
            metadata = BytesParser().parsebytes(archive.read(metadata_name))
            assert metadata['Name'] == 'contitext' and metadata['Version'] == version, 'wheel metadata mismatch'
            assert '<!-- mcp-name: io.github.jessysw/contitext -->' in metadata.get_payload(), 'missing Registry ownership marker'
            for source in (root / 'src/contitext').rglob('*.py'):
                assert archive.read(source.relative_to(root / 'src').as_posix()) == source.read_bytes(), 'wheel source differs from checkout'
        assert any(x.endswith('contitext/migrations/versions/0003_workspaces.py') for x in names), 'missing migration'
        assert any(x.endswith('contitext/migrations/versions/0004_context_metadata.py') for x in names), 'missing context metadata migration'
        assert any(x.endswith('contitext/upgrade.py') for x in names), 'missing upgrade command'
    else:
        with tarfile.open(path) as archive:
            members = archive.getmembers()
            assert all(not x.issym() and not x.islnk() for x in members), 'unexpected archive links'
            names = [x.name for x in members]
        assert any(x.endswith('/docs/acceptance-0.8.md') for x in names), 'missing acceptance guide'
        assert any(x.endswith('/scripts/check_distribution.py') for x in names), 'missing distribution check'
    for member in names:
        parts = PurePosixPath(member).parts
        assert not member.startswith('/') and '..' not in parts, 'unsafe archive path'
        assert not set(parts) & {'.git', '.venv', 'private-clients', 'reader-vault', 'backups', 'runtime'}, 'private directory in archive'
        assert all(not x.startswith('.env') or x == '.env.example' for x in parts), 'private environment in archive'
        assert not member.endswith(('.dump', '.log', '.pyc')), 'runtime data in archive'
        assert not any(x.startswith('client') and x.endswith('.json') for x in parts), 'client configuration in archive'
    print(f'{name}: checked {len(names)} archive members')

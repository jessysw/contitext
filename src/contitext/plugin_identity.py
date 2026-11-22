"""Persist only runtime-declared Hermes compression lineage, never project guesses."""
import argparse
import json
from pathlib import Path
import sys

from contitext.hooks import ID
from contitext.outbox import atomic_json, digest, private_directory
from contitext.resolution import mapping_lock, read_local_json


def resolve(directory, event):
    private_directory(directory)
    session = event.get('session_id')
    if not isinstance(session, str) or not ID.fullmatch(session):
        raise ValueError('invalid identity')
    path = directory / (digest(session) + '.identity.json')
    with mapping_lock(directory / 'identities'):
        if path.exists() or path.is_symlink():
            value = read_local_json(path, private=True)
            if value.get('session') != session or not ID.fullmatch(value.get('root', '')):
                raise ValueError('identity conflict')
            return value['root']
        root = session
        # Only an explicit compression transition preserves the prior scope.
        # Resume/branch/reset never inherit merely because a parent was supplied.
        parent = event.get('parent_session_id')
        if event.get('reason') == 'compression' and event.get('reset') is False:
            if not isinstance(parent, str) or not ID.fullmatch(parent):
                raise ValueError('compression identity required')
            prior = read_local_json(directory / (digest(parent) + '.identity.json'), private=True)
            if prior.get('session') != parent or not ID.fullmatch(prior.get('root', '')):
                raise ValueError('unknown compression parent')
            root = prior['root']
        if sum(1 for _ in directory.glob('*.identity.json')) >= 4096:
            raise ValueError('identity capacity reached')
        atomic_json(path, {'session': session, 'root': root})
        return root


def main():
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument('--directory', type=Path, required=True)
        args = parser.parse_args()
        data = sys.stdin.buffer.read(4097)
        if len(data) > 4096:
            raise ValueError('oversized input')
        value = json.loads(data)
        print(json.dumps({'root': resolve(args.directory, value)}))
    except Exception:
        print('{}')


if __name__ == '__main__':
    main()

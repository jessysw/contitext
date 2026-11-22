"""Explicit user-level hook installation, with preservation and private backups."""
import json
from pathlib import Path
import shlex
import sys
import tempfile
import os
from contextlib import nullcontext

from contitext.resolution import ResolutionError, load_connection, load_mappings, mapping_lock, read_local_json


def install(args):
    for path in (args.config, args.connection, args.mappings):
        if not path.is_absolute():
            raise ResolutionError('hook configuration paths must be absolute')
    connection = load_connection(args.connection)
    load_mappings(args.mappings, connection)
    command = shlex.join([sys.executable, '-m', 'contitext.hooks', '--client', args.client,
                          '--connection', str(args.connection), '--mappings', str(args.mappings)])
    handler = {'type': 'command', 'command': command, 'timeout': 5}
    if args.client == 'codex':
        handler['additionalContextLimit'] = 4000
    entry = {'matcher': 'startup|resume|clear|compact|fork', 'hooks': [handler]}
    # Parent creation is an explicit installer action; never done by a running hook.
    if not args.config.parent.exists():
        if args.dry_run:
            return {'changed': True, 'fragment': {'hooks': {'SessionStart': [entry]}}}
        args.config.parent.mkdir(parents=True, mode=0o700)
    with nullcontext() if args.dry_run else mapping_lock(args.config):
        data = read_local_json(args.config) if args.config.exists() or args.config.is_symlink() else {}
        hooks = data.setdefault('hooks', {})
        if not isinstance(hooks, dict):
            raise ResolutionError('existing hooks must be a JSON object')
        entries = hooks.setdefault('SessionStart', [])
        if not isinstance(entries, list):
            raise ResolutionError('existing SessionStart hooks must be a list')
        if entry in entries:
            return {'changed': False}
        for group in entries:
            if not isinstance(group, dict) or not isinstance(group.get('hooks'), list):
                raise ResolutionError('existing SessionStart hook group is malformed')
            if any(isinstance(h, dict) and 'contitext.hooks' in str(h.get('command', '')) for h in group['hooks']):
                raise ResolutionError('another Contitext hook is configured; review and remove it explicitly before replacing')
        entries.append(entry)
        if args.dry_run:
            return {'changed': True, 'configuration': data}
        backup = None
        if args.config.exists():
            fd, backup = tempfile.mkstemp(prefix=args.config.name + '.backup-', dir=args.config.parent)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(args.config.read_bytes())
                stream.flush(); os.fsync(stream.fileno())
        fd, temporary = tempfile.mkstemp(prefix='.contitext-hooks-', dir=args.config.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(data, stream, indent=2); stream.write('\n')
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, args.config)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return {'changed': True, 'config': str(args.config), 'backup': backup,
                'next_action': 'Review and trust the hook in your client, then start a new session.'}

"""Explicit user-level hook installation, with preservation and private backups."""
import json
from pathlib import Path
import shlex
import sys
import tempfile
import os
from contextlib import nullcontext

from contitext.resolution import ResolutionError, load_connection, load_mappings, mapping_lock, read_local_json
from contitext.hook_contracts import additions as native_additions


def install(args):
    for path in (args.config, args.connection, args.mappings):
        if not path.is_absolute():
            raise ResolutionError('hook configuration paths must be absolute')
    connection = load_connection(args.connection)
    load_mappings(args.mappings, connection)
    command = shlex.join([sys.executable, '-I', '-m', 'contitext.hooks', '--client', args.client,
                          '--connection', str(args.connection), '--mappings', str(args.mappings)])
    state_dir = getattr(args,'state_dir',None)
    if getattr(args,'checkpoints',False):
        if state_dir is None or not state_dir.is_absolute():
            raise ResolutionError('--checkpoints requires an explicit private --state-dir')
        if not state_dir.exists() and not args.dry_run:
            state_dir.mkdir(parents=True,mode=0o700)
        if state_dir.exists():
            from contitext.outbox import private_directory
            private_directory(state_dir)
        command += ' --state-dir ' + shlex.quote(str(state_dir)) + ' --timeout 2'
    elif state_dir is not None:
        raise ResolutionError('--state-dir requires --checkpoints')
    additions = native_additions(args.client, command, getattr(args,'checkpoints',False))
    flat = args.client in ('copilot', 'cursor')
    # Parent creation is an explicit installer action; never done by a running hook.
    if not args.config.parent.exists():
        if args.dry_run:
            return {'changed': True, 'fragment': {**({'version': 1} if flat else {}), 'hooks': additions}}
        args.config.parent.mkdir(parents=True, mode=0o700)
    with nullcontext() if args.dry_run else mapping_lock(args.config):
        data = read_local_json(args.config) if args.config.exists() or args.config.is_symlink() else {}
        if flat:
            if data.get('version', 1) != 1:
                raise ResolutionError('unsupported hook configuration version')
            data.setdefault('version', 1)
        hooks = data.setdefault('hooks', {})
        if not isinstance(hooks, dict):
            raise ResolutionError('existing hooks must be a JSON object')
        changed = False
        for event, groups in additions.items():
            entries = hooks.setdefault(event, [])
            if not isinstance(entries, list):
                raise ResolutionError('existing hooks must be lists')
            for group in entries:
                if not isinstance(group, dict) or (not flat and not isinstance(group.get('hooks'), list)):
                    raise ResolutionError('existing hook group is malformed')
                handlers = [group] if flat else group['hooks']
                if group not in groups and any(isinstance(h, dict) and 'contitext.hooks' in str(h.get('command', '')) for h in handlers):
                    raise ResolutionError('another Contitext hook is configured; review and remove it explicitly before replacing')
            for group in groups:
                if group not in entries:
                    entries.append(group)
                    changed = True
        if not changed:
            return {'changed':False}
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

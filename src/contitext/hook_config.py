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
    timeout = getattr(args,'worker_timeout',None)
    if timeout is not None and not 0.1 <= timeout <= 10:
        raise ResolutionError('timeout must be between 0.1 and 10 seconds')
    additions = native_additions(args.client, command, getattr(args,'checkpoints',False), timeout)
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
        backup = save(args.config, data)
        return {'changed': True, 'config': str(args.config), 'backup': backup,
                'next_action': 'Review and trust the hook in your client, then start a new session.'}


def save(config, data):
    backup = None
    if config.exists():
        fd, backup = tempfile.mkstemp(prefix=config.name + '.backup-', dir=config.parent)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(config.read_bytes())
            stream.flush(); os.fsync(stream.fileno())
    fd, temporary = tempfile.mkstemp(prefix='.contitext-hooks-', dir=config.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2); stream.write('\n')
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, config)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return backup


def disable(args):
    from contitext.hook_diagnostics import configured_events, owned
    if not args.config.is_absolute():
        raise ResolutionError('configuration path must be absolute')
    if not args.config.exists() and not args.config.is_symlink():
        return {'changed': False, 'removed': 0}
    with nullcontext() if args.dry_run else mapping_lock(args.config):
        data = read_local_json(args.config)
        events = configured_events(data, args.client)
        if not events:
            return {'changed': False, 'removed': 0}
        flat = args.client in ('copilot','cursor')
        for event in events:
            entries = []
            for entry in data['hooks'][event]:
                if flat:
                    if not owned(entry, args.client): entries.append(entry)
                elif isinstance(entry,dict) and isinstance(entry.get('hooks'),list):
                    retained = [h for h in entry['hooks'] if not owned(h,args.client)]
                    if retained or not entry['hooks']: entries.append({**entry,'hooks':retained})
                else:
                    entries.append(entry)
            if entries: data['hooks'][event] = entries
            else: del data['hooks'][event]
        result = {'changed': True, 'removed': sum(events.values()),
                  'note': 'Reload the runtime. MCP configuration and pending progress are retained.'}
        if args.dry_run:
            return {**result, 'configuration': data}
        return {**result, 'backup': save(args.config,data)}

"""Private, opt-in progress candidates; durable before network, never rebind on replay."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from contitext.resolution import ResolutionError, connection_key, load_connection, mapping_lock, read_local_json
from contitext.session_client import call

MAX_PENDING = 256


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def private_directory(path):
    if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink():
        raise ResolutionError('explicit private state directory required')
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ResolutionError('state directory must be caller-owned with mode 0700')
    return path


def state_path(directory, connection, scope):
    return private_directory(directory) / (digest([connection_key(connection),scope]) + '.state.json')


def sync_directory(directory):
    fd = os.open(directory, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def atomic_json(path, value):
    fd, temporary = tempfile.mkstemp(prefix='.contitext-state-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True); stream.write('\n')
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary,path)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def remember(args, connection, binding):
    path = state_path(args.state_dir, connection, binding['scope_id'])
    with mapping_lock(path):
        if path.exists() or path.is_symlink():read_local_json(path,private=True)
        atomic_json(path, {'version':1,'connection':connection_key(connection),'binding':binding})


def redact(text):
    text = re.sub(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)', '[REDACTED PRIVATE KEY]', text)
    text = re.sub(r'\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{12,}|AKIA[A-Z0-9]{16})\b', '[REDACTED TOKEN]', text)
    text = re.sub(r'(?i)\bbearer\s+[^\s"\x27,;]+', 'Bearer [REDACTED]', text)
    text = re.sub(r'(?i)([a-z][a-z0-9+.-]*://)[^/@\s]+:[^/@\s]+@', r'\1[REDACTED]@', text)
    text = re.sub(r'''(?ix)(["']?(?:[a-z0-9_]*(?:token|password|secret|api_key))["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)''', r'\1[REDACTED]', text)
    encoded = text.encode('utf-8')
    return encoded[:2400].decode('utf-8','ignore') + (' [truncated]' if len(encoded)>2400 else '')


def stage(args, event):
    from contitext.hooks import identity
    if event.get('hook_event_name') not in {'Stop','Checkpoint'}:
        return None
    summary = event.get('last_assistant_message')
    if not isinstance(summary,str) or not summary.strip():
        return None
    scope, session = identity(args.client,event)
    connection = load_connection(args.connection)
    path = state_path(args.state_dir, connection, scope)
    with mapping_lock(path), mapping_lock(args.state_dir / 'outbox'):
        state = read_local_json(path,private=True)
        if state.get('version') != 1 or state.get('connection') != connection_key(connection):
            return None
        binding = state.get('binding')
        if not isinstance(binding,dict) or any(not isinstance(binding.get(k),str) or not binding[k] for k in ('scope_id','session_id','principal_id','project_id','updated_at')):
            raise ResolutionError('invalid saved binding; restart the session hook to refresh it')
        if binding.get('scope_id') != scope:
            return None
        summary = redact(summary)
        source = event.get('turn_id') or event.get('source_id') or digest(summary)
        source = digest([event['hook_event_name'],source,summary])
        request = {'project_id':binding['project_id'],'scope_id':scope,'session_id':session,
                   'agent_id':binding['principal_id'],'source_kind':'hook','source_id':f'{args.client}:{source}',
                   'event_kind':'checkpoint','payload':{'summary':summary,'capture':'automatic_candidate',
                   'hook_event':event['hook_event_name']},
                   'event_metadata':{'candidate':True,'task_id':getattr(args,'task_id',None)},
                   'expected_binding_updated_at':binding['updated_at']}
        key = digest([connection_key(connection),binding,request])
        request['idempotency_key'] = 'hook-' + key
        target = args.state_dir / (key + '.pending.json')
        value = {'version':1,'connection':connection_key(connection),'binding':binding,'request':request}
        if target.exists() or target.is_symlink():
            if read_local_json(target,private=True) != value:
                raise ResolutionError('pending checkpoint conflict')
            return target
        if sum(1 for _ in args.state_dir.glob('*.pending.json')) >= MAX_PENDING:
            raise ResolutionError('outbox capacity reached; inspect pending checkpoints')
        # The per-scope lock serializes capture for this session; atomic replace
        # persists a complete private candidate before any network operation.
        atomic_json(target,value)
        return target


async def flush(client, args, connection, binding):
    tools = await client.list_tools()
    tool = next((t for t in tools.tools if t.name == 'context_record'),None)
    properties = tool.inputSchema.get('properties',{}) if tool else {}
    if not {'event_metadata','expected_binding_updated_at'} <= set(properties):
        return 0
    directory = private_directory(args.state_dir)
    sent = 0
    for path in sorted(directory.glob('*.pending.json'))[:MAX_PENDING]:
        if sent >= 8:break
        try:
            value = read_local_json(path,private=True)
            if value.get('version') != 1 or value.get('connection') != connection_key(connection) or value.get('binding') != binding:
                continue
            request = value['request']
            if (request.get('scope_id') != binding['scope_id'] or request.get('project_id') != binding['project_id']
                    or request.get('agent_id') != binding['principal_id']
                    or request.get('expected_binding_updated_at') != binding['updated_at']
                    or request.get('event_kind') != 'checkpoint'
                    or request.get('event_metadata',{}).get('candidate') is not True):
                continue
            # Check again for each replay. The server also compares the binding
            # timestamp while holding its row lock, closing the read/write race.
            if await call(client,'project_current',{'scope_id':binding['scope_id']}) != binding:
                return sent
            result = await call(client,'context_record',request)
            if result.get('idempotency_key') == request['idempotency_key']:
                path.unlink(missing_ok=True)
                sync_directory(directory)
                sent += 1
        except (OSError, ResolutionError, KeyError, TypeError, AttributeError):
            continue  # Preserve unacknowledged work for a later attempt.
    return sent


def status(directory):
    private_directory(directory)
    from contitext.hook_diagnostics import last_run
    diagnostic = last_run(directory)
    return {'pending':sum(1 for _ in directory.glob('*.pending.json')),
            'sessions':sum(1 for _ in directory.glob('*.state.json')),
            'limit':MAX_PENDING,
            'last_run': diagnostic,
            'note':'Local counts only; pending items may be offline, revoked or pinned to an old binding. No content is printed.'}

"""Content-free local hook outcomes and read-only connection diagnostics."""
import asyncio
from datetime import datetime, timezone
import json
import shlex

from contitext.hook_contracts import CLIENTS, PLUGIN_CLIENTS
from contitext.outbox import atomic_json, private_directory, status
from contitext.resolution import ResolutionError, load_connection, load_mappings, read_local_json
from contitext.session_client import connect

EVENTS = {'SessionStart','Stop','Checkpoint','PreCompact','SessionEnd','Interrupt'}
OUTCOMES = {'context_loaded','completed_without_context','worker_error','timeout','invalid_input'}


def last_run(directory):
    path = directory/'last-run.json'
    if not path.exists() and not path.is_symlink():
        return None
    value = read_local_json(path, private=True)
    try:
        at = datetime.fromisoformat(value['at']).isoformat()
        if (value.get('version') != 1 or value.get('client') not in CLIENTS + PLUGIN_CLIENTS
                or value.get('event') not in EVENTS | {'unsupported'} or value.get('outcome') not in OUTCOMES
                or value.get('capture') not in {'failed','not_failed'}):
            raise ValueError('invalid diagnostic')
        return {**{key:value[key] for key in ('version','client','event','outcome','capture')},'at':at}
    except (KeyError, TypeError, ValueError):
        return {'outcome':'invalid_diagnostic'}


def record_run(args, data, outcome):
    directory = getattr(args, 'state_dir', None)
    if directory is None:
        return
    try:
        private_directory(directory)
        path = directory/'last-run.json'
        if path.exists() or path.is_symlink():
            read_local_json(path, private=True)
        event = json.loads(data).get('hook_event_name')
        atomic_json(path, {'version': 1, 'at': datetime.now(timezone.utc).isoformat(),
            'client': args.client if args.client in CLIENTS + PLUGIN_CLIENTS else 'unknown',
            'event': event if event in EVENTS else 'unsupported', 'outcome': outcome,
            'capture': 'failed' if getattr(args,'capture_failed',False) else 'not_failed'})
    except Exception:
        pass  # Diagnostics must not obstruct an advisory hook.


def owned(handler, client):
    """Recognize only the canonical generated command, not a substring or shell wrapper."""
    if not isinstance(handler, dict) or handler.get('type') != 'command':
        return False
    command = handler.get('command')
    if not isinstance(command, str):
        return False
    try:
        argv = shlex.split(command)
        return (len(argv) >= 6 and argv[1:4] == ['-I','-m','contitext.hooks']
                and argv[4:6] == ['--client',client] and command == shlex.join(argv))
    except ValueError:
        return False


def configured_events(data, client):
    hooks = data.get('hooks', {})
    if not isinstance(hooks, dict):
        raise ResolutionError('hooks must be an object')
    events = {}
    flat = client in ('copilot','cursor')
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            raise ResolutionError('hook entries must be lists')
        count = sum(1 for entry in entries if isinstance(entry,dict)
                    for handler in ([entry] if flat else entry.get('hooks',[])) if owned(handler,client))
        if count: events[event] = count
    return events


async def doctor(args):
    if not all(path.is_absolute() for path in (args.config,args.connection,args.mappings)):
        raise ResolutionError('diagnostic paths must be absolute')
    data = read_local_json(args.config) if args.config.exists() or args.config.is_symlink() else {}
    connection = load_connection(args.connection)
    load_mappings(args.mappings, connection)
    report = {'client': args.client, 'configured_events': configured_events(data,args.client),
              'connection': 'unavailable', 'runtime_activation': 'not_verified',
              'note': 'Configuration is not proof of runtime trust or invocation. Review the client hook status.'}
    try:
        async with asyncio.timeout(args.timeout):
            async with connect(connection) as client:
                catalog = await client.list_tools()
                names = {tool.name for tool in catalog.tools}
                required = {'project_current','project_bind','context_get','context_record'}
                report['connection'] = 'ready' if required <= names else 'missing_tools'
                report['missing_tools'] = sorted(required - names)
    except TimeoutError:
        report['connection'] = 'timeout'
    except Exception:
        report['connection'] = 'unavailable'
    if args.state_dir is not None:
        report['state'] = status(args.state_dir)
    return report

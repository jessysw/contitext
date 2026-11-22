"""Export reviewable local runtime adapters; never enable or trust another agent."""
from importlib.resources import files
import json
from pathlib import Path
import os
import sys

from contitext import __version__
from contitext.resolution import ResolutionError, load_connection, load_mappings


def export(args):
    for path in (args.output, args.connection, args.mappings):
        if not path.is_absolute():
            raise ResolutionError('plugin paths must be absolute')
    connection = load_connection(args.connection)
    load_mappings(args.mappings, connection)
    if args.output.exists() or args.output.is_symlink():
        raise ResolutionError('export destination must be new; review a new export before replacing an installed plugin')
    command = [sys.executable, '-I', '-m', 'contitext.hooks', '--client', args.client,
               '--connection', str(args.connection), '--mappings', str(args.mappings), '--timeout', '3']
    checkpoints = getattr(args, 'checkpoints', False)
    state_dir = getattr(args, 'state_dir', None)
    if checkpoints:
        if state_dir is None or not state_dir.is_absolute():
            raise ResolutionError('--checkpoints requires a private absolute --state-dir')
        if state_dir.exists():
            from contitext.outbox import private_directory
            private_directory(state_dir)
        command.extend(['--state-dir', str(state_dir)])
    elif state_dir is not None:
        raise ResolutionError('--state-dir requires --checkpoints')
    resource = files('contitext').joinpath('plugin_templates')
    profile = {'command': command, 'checkpoints': checkpoints}
    content = {}
    if args.client == 'hermes':
        content['__init__.py'] = resource.joinpath('hermes.py').read_text()
        content['plugin.yaml'] = f'name: contitext\nversion: "{__version__}"\ndescription: Project continuity through an existing Contitext MCP connection\n'
        profile['identity_command'] = [sys.executable, '-I', '-m', 'contitext.plugin_identity',
                                       '--directory', str(args.output / 'identities')]
    else:
        content['bridge.mjs'] = resource.joinpath('bridge.mjs').read_text()
        content['index.mjs'] = resource.joinpath(args.client + '.mjs').read_text()
        content['package.json'] = json.dumps({'name': 'contitext-' + args.client, 'version': __version__,
            'private': True, 'type': 'module', 'exports': './index.mjs',
            **({'openclaw': {'extensions': ['./index.mjs']}} if args.client == 'openclaw' else {})}, indent=2) + '\n'
        if args.client == 'openclaw':
            content['openclaw.plugin.json'] = json.dumps({'id': 'contitext', 'name': 'Contitext',
                'description': 'Optional project continuity using an existing MCP connection',
                'configSchema': {'type': 'object', 'additionalProperties': False, 'properties': {}}}, indent=2) + '\n'
    content['bridge.json'] = json.dumps(profile, indent=2) + '\n'
    if args.dry_run:
        return {'changed': True, 'client': args.client, 'files': sorted(content), 'enabled': False}
    args.output.mkdir(parents=True, mode=0o700)
    if state_dir and not state_dir.exists():
        state_dir.mkdir(parents=True, mode=0o700)
    if args.client == 'hermes':
        (args.output / 'identities').mkdir(mode=0o700)
    for name, value in content.items():
        with os.fdopen(os.open(args.output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            stream.write(value)
    return {'changed': True, 'client': args.client, 'output': str(args.output), 'enabled': False,
            'next_action': 'Review the exported code and activate it through the runtime. See docs/plugin-clients.md.'}

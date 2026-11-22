"""Native command-hook contracts. No transcript reads or permission decisions."""
from pathlib import Path
import math
import shlex

CLIENTS = ('codex', 'claude', 'copilot', 'cursor', 'gemini')
PLUGIN_CLIENTS = ('hermes', 'openclaw', 'opencode')
EVENTS = {
    'copilot': {'sessionStart': 'SessionStart', 'agentStop': 'Stop',
                'preCompact': 'PreCompact', 'sessionEnd': 'SessionEnd'},
    'cursor': {'sessionStart': 'SessionStart', 'afterAgentResponse': 'Stop',
               'preCompact': 'PreCompact', 'sessionEnd': 'SessionEnd'},
    'gemini': {'SessionStart': 'SessionStart', 'AfterAgent': 'Stop',
               'PreCompress': 'PreCompact', 'SessionEnd': 'SessionEnd'},
}


def normalize(client, event, native_event=None):
    if not isinstance(event, dict):
        raise ValueError('invalid event')
    if client in ('codex', 'claude', *PLUGIN_CLIENTS):
        return event
    name = native_event or event.get('hook_event_name')
    expected = EVENTS[client].get(name)
    if not expected:
        raise ValueError('unsupported native event')
    # An explicit event is needed for Copilot's event-name-free camelCase input.
    # Never reinterpret a contradictory payload as a different lifecycle event.
    supplied = event.get('hook_event_name')
    if supplied and supplied not in (name, expected):
        raise ValueError('conflicting event identity')
    result = {'hook_event_name': expected, 'cwd': event.get('cwd'),
              'session_id': event.get('session_id'), 'source': event.get('source', 'startup')}
    if client == 'copilot':
        camel, snake = event.get('sessionId'), event.get('session_id')
        if camel and snake and camel != snake:
            raise ValueError('conflicting session identity')
        result['session_id'] = camel or snake
        if result['source'] == 'new':
            result['source'] = 'startup'
        # agentStop supplies a transcript path, not a final response. Flush only.
    elif client == 'cursor':
        result['conversation_id'] = event.get('conversation_id')
        result['session_id'] = event.get('session_id') or result['conversation_id']
        roots = event.get('workspace_roots')
        if not result['cwd'] and isinstance(roots, list) and len(roots) == 1:
            root = roots[0]
            if isinstance(root, str) and Path(root).is_absolute():
                result['cwd'] = root
        if expected == 'Stop':
            result['last_assistant_message'] = event.get('text')
            result['turn_id'] = event.get('generation_id')
    elif client == 'gemini' and expected == 'Stop':
        result['last_assistant_message'] = event.get('prompt_response')
    return result


def output(client, value):
    text = value.get('hookSpecificOutput', {}).get('additionalContext')
    if not text:
        return {}
    if client == 'copilot':
        return {'additionalContext': text}
    if client == 'cursor':
        return {'additional_context': text}
    if client == 'gemini':
        return {'hookSpecificOutput': {'additionalContext': text}}
    return value


def additions(client, command, checkpoints, timeout=None):
    """Return runtime configuration; timeout units are deliberately per client."""
    if timeout is not None:
        # End/interrupt hooks in Codex have a hard runtime deadline of 3 seconds.
        base = additions(client, command, checkpoints)
        for event, groups in base.items():
            budget = min(timeout, 2) if client == 'codex' and event in ('SessionEnd','Interrupt') else timeout
            for group in groups:
                for handler in (group.get('hooks') or [group]):
                    argv = shlex.split(handler['command'])
                    if '--timeout' in argv:
                        argv[argv.index('--timeout') + 1] = str(budget)
                    else:
                        argv.extend(['--timeout', str(budget)])
                    handler['command'] = shlex.join(argv)
                    key = 'timeoutSec' if client == 'copilot' else 'timeout'
                    handler[key] = (math.ceil(budget) + 1) * (1000 if client == 'gemini' else 1)
        return base
    if client in ('codex', 'claude'):
        handler = {'type': 'command', 'command': command, 'timeout': 4 if checkpoints else 5}
        if client == 'codex':
            handler['additionalContextLimit'] = 4000
        result = {'SessionStart': [{'matcher': 'startup|resume|clear|compact|fork', 'hooks': [handler]}]}
        if checkpoints:
            for event in ['Stop', 'PreCompact', 'SessionEnd'] + (['Interrupt'] if client == 'codex' else []):
                end = client == 'codex' and event in ('SessionEnd', 'Interrupt')
                event_command = command
                if end:
                    argv = shlex.split(command)
                    argv[argv.index('--timeout') + 1] = '2'
                    event_command = shlex.join(argv)
                result[event] = [{'hooks': [{'type': 'command', 'command': event_command, 'timeout': 3 if end else 4}]}]
        return result
    result = {}
    for event, canonical in EVENTS[client].items():
        if canonical != 'SessionStart' and not checkpoints:
            continue
        handler = {'type': 'command', 'command': command + ' --event ' + event}
        if client == 'gemini':
            handler.update(timeout=5000, name='contitext-' + event)
            result[event] = [{'hooks': [handler]}]  # No regex matcher: Gemini uses exact lifecycle values.
        else:
            handler['timeoutSec' if client == 'copilot' else 'timeout'] = 5
            result[event] = [handler]
    return result

"""Opt-in Hermes memory provider. Reads project context; captures assistant text only."""
import json
from pathlib import Path
import subprocess
import threading

from agent.memory_provider import MemoryProvider


PROFILE = Path(__file__).with_name('bridge.json')


def invoke(command, event):
    try:
        data = json.dumps(event)
        if len(data.encode()) > 65536:
            return {}
        result = subprocess.run(command, input=data, capture_output=True, text=True, timeout=4.5)
        if result.returncode or len(result.stdout.encode()) > 30000:
            return {}
        value = json.loads(result.stdout)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


class ContitextMemoryProvider(MemoryProvider):
    def __init__(self):
        self._lock = threading.RLock()
        self._session = self._root = self._cwd = ''
        self._primary = False
        try:
            self._profile = json.loads(PROFILE.read_text())
        except Exception:
            self._profile = {}

    @property
    def name(self):
        return 'contitext'

    def is_available(self):
        return all(isinstance(self._profile.get(key), list) and self._profile[key]
                   and all(isinstance(x, str) for x in self._profile[key])
                   and Path(self._profile[key][0]).is_absolute() and Path(self._profile[key][0]).is_file()
                   for key in ('command', 'identity_command'))

    def unavailable_reason(self):
        return 'Export Contitext with a durable Python installation and review bridge.json.'

    def initialize(self, session_id, **kwargs):
        with self._lock:
            # Older hosts without explicit agent context do not get automatic access.
            self._primary = kwargs.get('agent_context') == 'primary'
            self._cwd = kwargs.get('cwd') or ''
            if self._primary:
                self._switch(session_id, reason='initialize')

    def _switch(self, session_id, **kwargs):
        self._session, self._root = '', ''
        result = invoke(self._profile.get('identity_command', []), {'session_id': session_id, **kwargs})
        if isinstance(result.get('root'), str):
            self._session, self._root = session_id, result['root']

    def on_session_switch(self, new_session_id, *, parent_session_id='', reset=False, **kwargs):
        with self._lock:
            if self._primary:
                if kwargs.get('reason') != 'compression':
                    # The new session may have a different workspace. Missing cwd
                    # permits explicit binding hydration only, never an old mapping.
                    self._cwd = kwargs.get('cwd') or ''
                self._switch(new_session_id, parent_session_id=parent_session_id,
                             reset=reset, reason=kwargs.get('reason', 'switch'))

    def _event(self, name, **kwargs):
        if not self._primary or not self._root:
            return {}
        return invoke(self._profile['command'], {'hook_event_name': name,
            'session_id': self._session, 'conversation_id': self._root, 'cwd': self._cwd, **kwargs})

    def prefetch(self, query, *, session_id=''):
        with self._lock:
            if session_id != self._session:
                return ''
            # Do not forward the query. Refresh every request so a manual switch wins.
            return self._event('SessionStart').get('hookSpecificOutput', {}).get('additionalContext', '')

    def sync_turn(self, user_content, assistant_content, *, session_id='', **kwargs):
        with self._lock:
            if session_id == self._session and self._profile.get('checkpoints') is True:
                self._event('Stop', last_assistant_message=assistant_content)

    def on_pre_compress(self, messages):
        with self._lock:
            if self._profile.get('checkpoints') is True:
                self._event('PreCompact')
        return ''

    def on_session_end(self, messages):
        with self._lock:
            if self._profile.get('checkpoints') is True:
                self._event('SessionEnd')

    def get_tool_schemas(self):
        return []  # Keep the existing authenticated MCP tool connection.

    def get_config_schema(self):
        return []  # Paths and capture consent are supplied by the explicit export.

    def save_config(self, values, hermes_home):
        if values:
            raise ValueError('Configure this adapter through contitext plugins export.')


def register(ctx):
    ctx.register_memory_provider(ContitextMemoryProvider())

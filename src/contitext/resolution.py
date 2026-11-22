"""Opt-in local project mappings; repository content never creates configuration."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from urllib.parse import urlsplit

MAX_CONFIG_BYTES = 65536
PROJECT_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}/[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class ResolutionError(ValueError):
    """Safe-to-display configuration or discovery failure."""


def read_local_json(path: Path, *, private: bool = False) -> dict:
    """Read a caller-owned regular file without following its final symlink."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise ResolutionError('configuration must be a regular file owned by the current user')
            if info.st_mode & (0o077 if private else 0o022):
                raise ResolutionError('unsafe configuration permissions; use mode 0600 for mappings')
            data = stream.read(MAX_CONFIG_BYTES + 1)
        if len(data) > MAX_CONFIG_BYTES:
            raise ResolutionError('configuration exceeds the supported size')
        def unique_object(pairs):
            obj = {}
            for key, value in pairs:
                if key in obj:
                    raise ResolutionError('duplicate JSON configuration key')
                obj[key] = value
            return obj
        result = json.loads(data, object_pairs_hook=unique_object)
        if not isinstance(result, dict):
            raise ResolutionError('configuration must be a JSON object')
        return result
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ResolutionError('cannot read trusted local configuration') from None


def load_connection(path: Path) -> dict:
    data = read_local_json(path)
    if set(data) == {'mcpServers'}:
        servers = data['mcpServers']
        if not isinstance(servers, dict) or set(servers) != {'contitext'}:
            raise ResolutionError('connection must name only the contitext MCP server')
        data = servers['contitext']
    if not isinstance(data, dict) or set(data) - {'command', 'args'}:
        raise ResolutionError('connection accepts command/args only; keep secrets in private server configuration')
    command, args = data.get('command'), data.get('args', [])
    if not isinstance(command, str) or not command.strip() or '\0' in command:
        raise ResolutionError('connection requires a nonempty executable')
    if not isinstance(args, list) or any(not isinstance(x, str) or '\0' in x for x in args):
        raise ResolutionError('connection arguments must be strings')
    return {'command': command, 'args': args}


def connection_key(connection: dict) -> str:
    return hashlib.sha256(json.dumps(connection, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def canonical_remote(value: str) -> str:
    """Normalize transport spellings, without network, aliases or basename guesses."""
    if not isinstance(value, str) or not value or any(c.isspace() for c in value) or any(c in value for c in '\0\\?#%'):
        raise ResolutionError('unsupported Git remote; use a plain HTTPS or SSH repository URL')
    scp = re.fullmatch(r'git@([A-Za-z0-9.-]+):([^:]+)', value)
    if scp:
        host, path, port = scp.group(1), scp.group(2), None
    else:
        try:
            parsed = urlsplit(value)
            if parsed.scheme not in {'https', 'ssh'} or not parsed.hostname or parsed.password:
                raise ValueError
            if parsed.scheme == 'https' and parsed.username or parsed.scheme == 'ssh' and parsed.username not in {None, 'git'}:
                raise ValueError
            host, path, port = parsed.hostname, parsed.path.lstrip('/'), parsed.port
            if port == (443 if parsed.scheme == 'https' else 22):
                port = None
        except ValueError:
            raise ResolutionError('unsupported Git remote; credentials and local paths are not accepted') from None
    if not re.fullmatch(r'[A-Za-z0-9.-]+', host) or host.startswith('.') or host.endswith('.'):
        raise ResolutionError('unsupported Git remote host')
    if path.endswith('.git'):
        path = path[:-4]
    parts = path.split('/')
    if len(parts) < 2 or any(not re.fullmatch(r'[A-Za-z0-9_.-]+', p) or p in {'.', '..'} for p in parts):
        raise ResolutionError('unsupported Git remote repository path')
    # A nondefault port remains part of the identity, including its transport.
    endpoint = host.lower() if port is None else f'{parsed.scheme}://{host.lower()}:{port}'
    return endpoint + '/' + '/'.join(parts)


def directory_key(value: str | Path, *, must_exist: bool = True) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ResolutionError('directory mappings require an absolute path')
    try:
        path = path.resolve(strict=must_exist)
        if must_exist and not path.is_dir():
            raise OSError
    except OSError:
        raise ResolutionError('mapped directory must exist') from None
    return str(path)


def load_mappings(path: Path, connection: dict, *, missing_ok: bool = False) -> dict:
    if missing_ok and not path.exists() and not path.is_symlink():
        return {'version': 1, 'connection': connection_key(connection), 'mappings': []}
    data = read_local_json(path, private=True)
    if set(data) != {'version', 'connection', 'mappings'} or type(data['version']) is not int or data['version'] != 1:
        raise ResolutionError('unsupported mapping file schema')
    if data['connection'] != connection_key(connection):
        raise ResolutionError('mapping file belongs to a different MCP connection')
    if not isinstance(data['mappings'], list) or len(data['mappings']) > 256:
        raise ResolutionError('mapping file must contain at most 256 mappings')
    seen = set()
    for entry in data['mappings']:
        if not isinstance(entry, dict) or set(entry) != {'kind', 'match', 'project'}:
            raise ResolutionError('invalid mapping entry')
        kind, match, project = entry['kind'], entry['match'], entry['project']
        if not isinstance(kind, str) or kind not in {'remote', 'directory'} or not isinstance(match, str) or not isinstance(project, str) or not PROJECT_REF.fullmatch(project):
            raise ResolutionError('mapping requires a qualified workspace/project reference')
        if kind == 'remote':
            # Canonical endpoints never contain user credentials; validate by round trip.
            source = match if match.startswith('ssh://') or match.startswith('https://') else 'https://' + match
            if canonical_remote(source) != match:
                raise ResolutionError('remote mapping is not canonical')
        elif not Path(match).is_absolute() or str(Path(match)) != match or '..' in Path(match).parts:
            raise ResolutionError('directory mapping must use its canonical absolute path')
        key = (kind, match)
        if key in seen:
            raise ResolutionError('duplicate mapping selector')
        seen.add(key)
    return data


@contextmanager
def mapping_lock(path: Path):
    """Serialize operator edits without trusting locks or directories from a repo."""
    if not path.is_absolute():
        raise ResolutionError('mapping file requires an absolute path')
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ResolutionError('create a private configuration directory first')
    info = parent.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ResolutionError('mapping directory must be owned by you and not writable by others')
    try:
        fd = os.open(str(path) + '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        with os.fdopen(fd, 'r+b') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ResolutionError('unsafe mapping lock')
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
    except (OSError, BlockingIOError):
        raise ResolutionError('cannot lock mapping configuration; retry after other edits finish') from None


def save_mappings(path: Path, data: dict):
    content = (json.dumps(data, indent=2, sort_keys=True) + '\n').encode()
    if len(content) > MAX_CONFIG_BYTES or len(data['mappings']) > 256:
        raise ResolutionError('mapping file exceeds the supported size')
    fd, temp = tempfile.mkstemp(prefix='.contitext-mappings-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def edit_mapping(args) -> dict:
    connection = load_connection(args.connection)
    if args.mapping_action == 'list':
        return load_mappings(args.mappings, connection)
    kind = 'remote' if args.remote is not None else 'directory'
    match = canonical_remote(args.remote) if kind == 'remote' else directory_key(args.directory, must_exist=args.mapping_action == 'add')
    if args.mapping_action == 'add' and not PROJECT_REF.fullmatch(args.project):
        raise ResolutionError('use an explicit workspace/project reference')
    with mapping_lock(args.mappings):
        data = load_mappings(args.mappings, connection, missing_ok=args.mapping_action == 'add')
        previous = next((e for e in data['mappings'] if (e['kind'], e['match']) == (kind, match)), None)
        if args.mapping_action == 'add':
            if previous and previous['project'] != args.project:
                raise ResolutionError('selector already maps to another project; remove it explicitly before replacing')
            if not previous:
                data['mappings'].append({'kind': kind, 'match': match, 'project': args.project})
        else:
            if previous is None:
                raise ResolutionError('mapping selector not found')
            data['mappings'].remove(previous)
        save_mappings(args.mappings, data)
    return {'updated': True, 'mapping_count': len(data['mappings'])}


@dataclass(frozen=True)
class Selection:
    status: str
    source: str | None = None
    project: str | None = None


def git_remotes(cwd: Path) -> list[str]:
    # Ignore ambient GIT_DIR/GIT_WORK_TREE and injected config. Never fetch or run hooks.
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env['LC_ALL'] = 'C'
    try:
        root = subprocess.run(['git', '-C', str(cwd), 'rev-parse', '--show-toplevel'], env=env, capture_output=True, timeout=2)
        if root.returncode:
            if b'not a git repository' in root.stderr:
                return []
            raise ResolutionError('cannot safely inspect repository identity')
        result = subprocess.run(['git', '-C', str(cwd), 'config', '--local', '--get-regexp', r'^remote\..*\.url$'], env=env, capture_output=True, timeout=2)
        if result.returncode not in {0, 1} or len(result.stdout) > MAX_CONFIG_BYTES:
            raise ResolutionError('cannot safely inspect repository remotes')
        remotes = []
        for line in result.stdout.decode('utf-8').splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                remotes.append(parts[1])
        return remotes
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        raise ResolutionError('repository discovery unavailable; use an explicit project selection') from None


def select_mapping(data: dict, cwd: Path) -> Selection:
    root = Path(directory_key(cwd))
    entries = data['mappings']
    if any(e['kind'] == 'remote' for e in entries):
        remotes = set()
        for remote in git_remotes(root):
            try:
                remotes.add(canonical_remote(remote))
            except ResolutionError:
                continue  # An unsupported remote can never create a match.
        candidates = {e['project'] for e in entries if e['kind'] == 'remote' and e['match'] in remotes}
        if len(candidates) > 1:
            return Selection('ambiguous', 'remote')
        if candidates:
            return Selection('matched', 'remote', next(iter(candidates)))
    matches = [e for e in entries if e['kind'] == 'directory' and (root == Path(e['match']) or Path(e['match']) in root.parents)]
    if not matches:
        return Selection('unmatched')
    depth = max(len(Path(e['match']).parts) for e in matches)
    projects = {e['project'] for e in matches if len(Path(e['match']).parts) == depth}
    if len(projects) != 1:
        return Selection('ambiguous', 'directory')
    return Selection('matched', 'directory', projects.pop())

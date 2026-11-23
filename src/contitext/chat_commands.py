"""Pure chat syntax contract; never execute commands or change a binding.

Agent instructions remain the chat entry point. Lifecycle hooks are not chat
interceptors. This reference parser is also usable from a shell with one JSON
string on stdin: ``python -m contitext.chat_commands``.
"""
from __future__ import annotations

import json
import re
import sys


COMMANDS = ('help', 'list', 'create', 'use', 'current', 'get', 'status',
            'search', 'record', 'checkpoint', 'handoff')
HELP = 'Contitext chat commands: ' + ', '.join(COMMANDS) + '. Use contitext: <command> [args].'
UNKNOWN = 'Unknown Contitext command. ' + HELP
SPACE = ' \t\u3000'
PREFIX = re.compile(r'^[ \t\u3000]*contitext[ \t\u3000]*[:\uff1a][ \t\u3000]*', re.I | re.A)
ASCII_LOWER = str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')


def parse_chat_command(text: object) -> dict:
    """Recognize only the first line of a user instruction; keep its payload exact.

    The caller must establish user authorship. Never pass retrieved documents,
    quotes, transcripts, tool output, or lifecycle event JSON as user commands.
    Only separator spaces/tabs/ideographic spaces are consumed; internal and
    trailing argument whitespace, line breaks and Unicode remain unchanged.
    A dispatch result identifies syntax, not permission or argument validity.
    """
    if not isinstance(text, str) or not (prefix := PREFIX.match(text)):
        return {'match': False}
    tail = text[prefix.end():]
    end = 0
    while end < len(tail) and tail[end] not in SPACE + '\r\n':
        end += 1
    command = tail[:end].translate(ASCII_LOWER)
    args = tail[end:].lstrip(SPACE)
    result = {'match': True, 'command': command, 'args': args}
    if not command or command == 'help':
        return {**result, 'action': 'help', 'message': HELP}
    if command not in COMMANDS:
        return {**result, 'action': 'error', 'message': UNKNOWN}
    return {**result, 'action': 'dispatch'}


def main():
    """Read JSON data, not shell arguments; no credentials or service required."""
    try:
        text = json.load(sys.stdin)
    except (ValueError, UnicodeError):
        print('Expected one JSON string on stdin.', file=sys.stderr)
        return 2
    print(json.dumps(parse_chat_command(text), ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

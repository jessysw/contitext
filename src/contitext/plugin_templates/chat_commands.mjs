// Pure reference contract for JavaScript/TypeScript consumers, not a chat hook.
// The caller establishes user authorship; never parse history or retrieved data.
export const commands = Object.freeze(['help', 'list', 'create', 'use', 'current',
  'get', 'status', 'search', 'record', 'checkpoint', 'handoff']);
export const help = `Contitext chat commands: ${commands.join(', ')}. Use contitext: <command> [args].`;
const prefix = /^[ \t\u3000]*contitext[ \t\u3000]*[:\uff1a][ \t\u3000]*/i;

export function parseChatCommand(text) {
  if (typeof text !== 'string') return {match: false};
  const match = prefix.exec(text);
  if (!match) return {match: false};
  const tail = text.slice(match[0].length);
  const boundary = tail.search(/[ \t\u3000\r\n]/);
  const end = boundary < 0 ? tail.length : boundary;
  const command = tail.slice(0, end).replace(/[A-Z]/g, c => c.toLowerCase());
  const args = tail.slice(end).replace(/^[ \t\u3000]+/, '');
  const result = {match: true, command, args};
  if (!command || command === 'help') return {...result, action: 'help', message: help};
  if (!commands.includes(command)) return {...result, action: 'error', message: `Unknown Contitext command. ${help}`};
  return {...result, action: 'dispatch'};
}

import { readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { isAbsolute } from 'node:path';

const profile = JSON.parse(readFileSync(new URL('./bridge.json', import.meta.url), 'utf8'));
export const checkpoints = profile.checkpoints === true;
export const validID = value => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/.test(value);
export const contextText = value => value?.hookSpecificOutput?.additionalContext || '';

export function bridge(event) {
  return new Promise(resolve => {
    const command = profile.command;
    const data = JSON.stringify(event);
    if (!validID(event.session_id) || Buffer.byteLength(data) > 65536 ||
        !Array.isArray(command) || !command.every(x => typeof x === 'string') || !isAbsolute(command[0])) {
      resolve({}); return;
    }
    let child, timer, complete = false, output = '';
    const finish = value => {
      if (complete) return;
      complete = true; clearTimeout(timer); resolve(value);
    };
    try {
      child = spawn(command[0], command.slice(1), { stdio: ['pipe', 'pipe', 'ignore'] });
      timer = setTimeout(() => { child.kill('SIGKILL'); finish({}); }, 4500);
      child.on('error', () => finish({}));
      child.stdin.on('error', () => finish({}));
      child.stdout.on('data', chunk => {
        output += chunk.toString();
        if (Buffer.byteLength(output) > 30000) { child.kill('SIGKILL'); finish({}); }
      });
      child.on('close', code => {
        try { finish(code === 0 ? JSON.parse(output) : {}); } catch { finish({}); }
      });
      child.stdin.end(data);
    } catch { if (child) child.kill('SIGKILL'); finish({}); }
  });
}

export async function bounded(operation, milliseconds = 700) {
  const controller = new AbortController();
  let timer;
  try {
    return await Promise.race([operation(controller.signal), new Promise(resolve => {
      timer = setTimeout(() => { controller.abort(); resolve(undefined); }, milliseconds);
    })]);
  } catch { return undefined; } finally { clearTimeout(timer); }
}

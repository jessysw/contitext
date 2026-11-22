import { bridge, bounded, checkpoints, contextText, validID } from './bridge.mjs';

// OpenCode 2's documented default-export id/setup contract. No V1 hook guessing.
export default {
  id: 'contitext',
  async setup(ctx) {
    const controller = new AbortController();
    const session = async sessionID => {
      if (!validID(sessionID)) return;
      // The Promise SDK unwraps the HTTP response's single `data` field.
      const info = await bounded(signal => ctx.session.get({sessionID}, {signal}));
      // A plugin instance's location is not necessarily the event's location.
      if (info?.id !== sessionID || info.location?.directory !== ctx.location.directory) return;
      return info;
    };
    const start = await ctx.session.hook('context', async event => {
      const info = await session(event.sessionID);
      if (!info || !Array.isArray(event.system)) return;
      const text = contextText(await bridge({hook_event_name: 'SessionStart',
        session_id: info.id, cwd: info.location.directory}));
      if (!controller.signal.aborted && text) event.system.push({type: 'text', text});
    });
    const compact = checkpoints ? await ctx.session.hook('compaction', async event => {
      if (await session(event.sessionID))
        await bridge({hook_event_name: 'PreCompact', session_id: event.sessionID});
    }) : undefined;
    if (checkpoints) {
      void (async () => {
        try {
          for await (const event of ctx.event.subscribe({signal: controller.signal,
            types: ['session.text.ended', 'session.execution.succeeded', 'session.execution.failed', 'session.execution.interrupted']})) {
            const id = event.data?.sessionID;
            if (controller.signal.aborted || !await session(id)) continue;
            if (event.type === 'session.text.ended') {
              await bridge({hook_event_name: 'Stop', session_id: id, source_id: event.id,
                last_assistant_message: event.data.text});
            } else {
              await bridge({hook_event_name: 'SessionEnd', session_id: id});
            }
          }
        } catch { /* Runtime shutdown/unavailable event stream never breaks a turn. */ }
      })();
    }
    return async () => { controller.abort(); await start.dispose(); await compact?.dispose(); };
  },
};

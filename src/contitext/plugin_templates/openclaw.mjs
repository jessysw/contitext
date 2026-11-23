import { bridge, checkpoints, contextText, validID } from './bridge.mjs';
export { parseChatCommand } from './chat_commands.mjs';

export default {
  id: 'contitext', name: 'Contitext',
  register(api) {
    api.on('before_prompt_build', async (_event, ctx) => {
      if (!validID(ctx.sessionId) || typeof ctx.workspaceDir !== 'string') return;
      const text = contextText(await bridge({hook_event_name: 'SessionStart',
        session_id: ctx.sessionId, cwd: ctx.workspaceDir}));
      try {
        ctx.assertMemoryAudienceCurrent?.();
        ctx.hookInvocation?.assertActive();
      } catch { return; }
      if (text) return {prependContext: text};
    });
    if (!checkpoints) return;
    // A candidate from a finalization attempt is not an approved handoff.
    api.on('before_agent_finalize', async (event, ctx) => {
      if (!validID(event.sessionId) || (ctx.sessionId && ctx.sessionId !== event.sessionId)) return;
      await bridge({hook_event_name: 'Stop', session_id: event.sessionId,
        turn_id: event.turnId || event.runId, last_assistant_message: event.lastAssistantMessage});
    });
    api.on('before_compaction', async (_event, ctx) => {
      if (validID(ctx.sessionId)) await bridge({hook_event_name: 'PreCompact', session_id: ctx.sessionId});
    });
    api.on('session_end', async (event, ctx) => {
      if (validID(event.sessionId) && ctx.sessionId === event.sessionId)
        await bridge({hook_event_name: 'SessionEnd', session_id: event.sessionId});
    });
  },
};

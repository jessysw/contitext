# 0.8.2 client coverage plan

Status: implementation complete in PRs #21–#24; stable 0.8.2 release acceptance
is tracked in the final release PR and [release evidence](acceptance-0.8.2.md).
Track the complete effort in [issue #20](https://github.com/jessysw/contitext/issues/20).

Delivery sequence: four complete implementation PRs followed by one release-preparation PR:

1. **MCP and instruction coverage:** Copilot, Cursor, OpenCode and Gemini CLI;
   preserve the existing clients, handle versioned configuration layouts, and
   distinguish MCP availability from automatic context loading.
2. **Command hooks:** adapt the supported native lifecycle contracts of Copilot,
   Cursor and Gemini; preserve exact session identity, bounded startup and
   failure-open behavior. Never bypass runtime trust.
3. **Plugin runtimes:** Hermes, OpenClaw and OpenCode integration using their
   actual lifecycle and context-injection interfaces. Do not infer identity or
   promise unavailable progress/transcript data.
4. **Usability and acceptance:** installation/status/diagnostic/disable flows,
   real-client evidence where available, and contract/integration tests for
   outages, manual binding changes and durable candidate retries. State any
   missing runtime, login or trust prerequisite precisely.
5. **Release:** align metadata and English documentation, run the full CI matrix,
   native/Docker installed-artifact acceptance and privacy checks, then verify
   PyPI, MCP Registry and GitHub Release.

Each implementation PR contains its own documentation and tests. Main retains
one focused squash commit per completed PR. A merged feature is not a published
package or a production upgrade. Personal deployment rehearsals and configuration
remain outside this public repository.

No new hosted service, paid memory engine, exact-tokenizer requirement or automatic
promotion of candidate progress is part of this release. Existing project ACLs,
manual bindings and opt-in capture remain authoritative boundaries.

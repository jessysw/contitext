# 0.8.x automation and context plan

Status: the four functional deliveries form release 0.8.1, following the published
0.8.0 baseline. Release preparation and publication evidence are tracked below.

Track all deliveries in [issue #14](https://github.com/jessysw/contitext/issues/14).

## Delivery order

Deliver four focused functional PRs followed by one release-preparation PR.
Each functional PR includes implementation, documentation and regression tests.
Version numbers follow the validated release scope; these batches do not imply
one release per feature or a fixed 0.8.1 / 0.8.2 / 0.8.3 split.

| Batch | Complete deliverable | Acceptance |
| --- | --- | --- |
| A: project resolution | Opt-in local mappings, connection identity, remote normalization, directory fallback, authorized preview, atomic bind-if-unbound | Explicit selection and existing bindings win; ambiguous, unauthorized and unsupported identities never select a project; concurrent manual selection wins |
| B: session start | Bounded MCP context loading and opt-in adapters for verified runtime hooks | Fresh and resumed sessions load only their bound project; failure, timeout or unavailable service never blocks the agent; unrelated client configuration is preserved |
| C: context assembly | Effective decisions, unresolved questions, task-relevant handoff, deterministic budget | Explicit lifecycle relations and task scope; historical events remain readable; no unrelated task's handoff; output stays within its documented budget |
| D: checkpoints and session end | Opt-in progress candidates at checkpoints, compaction and supported end/interruption events; durable retry | Idempotent retries; pinned scope/project; no rebind to replay old work; automatic candidates never become approved decisions |
| Release | Align version, docs, packages and Registry; complete native/Docker rehearsals | Full CI, privacy checks, clean installation and real MCP write/read; publish only after the complete selected scope passes |

A precedes B because automatic discovery must not overwrite a manual selection.
C precedes D because saving more progress is not useful unless the next session
can select the relevant state. Hooks differ between runtimes: document verified
support rather than claiming every MCP client provides the same lifecycle.

## Boundaries

- Keep explicit `!! contitext use` authoritative. The agent itself never guesses
  a project from prose, directory names or a repository basename. A user-configured
  runtime resolver may establish a binding before the agent reads it.
- Mappings are private operator configuration outside repositories, scoped to an
  exact MCP connection and qualified workspace/project. They do not grant access.
- Recheck authorization and binding at use time. Conflicts fail closed for context
  selection and fail open for agent startup.
- Use the existing native, Docker and SSH MCP connection forms. No new service,
  hosted control plane, paid LLM, embedding engine or memory database is required.
- Preserve the eight MCP tool names and existing default call behavior. Optional
  capabilities must be discoverable; old servers never get a blind unsafe fallback.
- Treat retrieved content as untrusted project data. Automatic progress is a
  candidate, not an authoritative decision or evidence of completed work.
- Test against synthetic disposable deployments. Development does not install
  hooks into live agents or upgrade a production database.

## Evidence and status

- A: merged in [PR #15](https://github.com/jessysw/contitext/pull/15); all seven CI
  jobs passed. See [project resolution](project-resolution.md).
- B: merged in [PR #16](https://github.com/jessysw/contitext/pull/16); all seven CI
  jobs passed. See [session start hooks](session-hooks.md). Native hooks cover
  Codex and Claude; other MCP clients retain the explicit workflow.
- C: merged in [PR #17](https://github.com/jessysw/contitext/pull/17); all seven CI
  jobs passed. See [context assembly](context-assembly.md).
- D: merged in [PR #18](https://github.com/jessysw/contitext/pull/18); all seven CI
  jobs passed. See [automatic checkpoints](checkpoints.md).
- Release acceptance: [0.8.1 evidence](acceptance-0.8.1.md).
- Published baseline: [0.8.0 release](https://github.com/jessysw/contitext/releases/tag/v0.8.0).
- Existing self-hosting and migration work: [0.8.0 plan](v0.8-plan.md).

Optional memory integrations, public hosting, billing, OAuth/SSO, topic-based
switching, archive/delete and synchronization with another memory store remain
outside this effort. No external tester headcount or prerelease series is required.

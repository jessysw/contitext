# API contracts

All `/v1` endpoints require `Authorization: Bearer <token>`. Token configuration
maps a credential to a principal UUID; caller-supplied metadata cannot override
that identity. Health endpoints expose readiness only and do not require a token.

| Method | Path | Access |
| --- | --- | --- |
| PUT / GET | `/v1/scopes/{scope_id}/binding` | Reader on the selected project |
| GET | `/v1/projects/{project_id}/context` | Reader |
| GET | `/v1/projects/{project_id}/search?q=...&limit=20&cursor=...` | Reader |
| POST | `/v1/projects/{project_id}/events` | Writer |
| POST | `/v1/projects/{project_id}/handoffs` | Writer |
| POST | `/v1/projects/{project_id}/projection` | Owner; optional filesystem setup |
| GET | `/health/live`, `/health/ready` | Public health status |

Events require `scope_id`, `session_id`, `agent_id`, `source_kind`, `source_id`,
`event_kind`, a dictionary `payload`, and `idempotency_key`. Allowed generic event
kinds are `note`, `decision`, `question`, and `checkpoint`. Use the dedicated
handoff endpoint/tool for `handoff`.

Handoffs require the same provenance fields, `summary`, `next_action`, and an
idempotency key. `completed`, `current`, and `blockers` are lists of strings.

Idempotency keys are unique within a project. Identical retries by the same
principal return the original event. Changed payload, provenance, event kind, or
principal produces HTTP 409 (an MCP tool error), leaving the original event intact.

Unknown and unauthorized projects both produce HTTP 404 to avoid enumeration.
An unbound scope also produces 404. Invalid input produces 422. Missing or invalid
bearer credentials produce 401. An unavailable projector or maintenance fence
produces 503.

## Explicit boundaries in v0.5

- Scope selection is an agent-protocol requirement. The service authorizes every
  request's explicit project ID; it does not yet require that an event's project
  match a persisted scope binding. Callers must check `project_current` before
  writing. Stricter atomic binding validation is planned before migration of
  existing deployments.
- `context_get` returns the latest project checkpoint and handoff, the 20 latest
  decisions, and up to 20 question events whose own payload is not marked
  `resolved: true`. Events are immutable. Appending a later resolution does not
  close an earlier question automatically; question/decision lifecycle reduction
  is planned. Search retains the full history.
- Search is lexical, not semantic. Results rank matching JSON payload text using
  PostgreSQL's `simple` dictionary. Unicode is stored, but CJK segmentation and
  embeddings are outside this release.
- A scope is unique per authenticated principal. Agents that share a credential
  should use globally distinct conversation scope IDs.
- MCP transport is stdio. REST is HTTP. An authenticated remote MCP transport and
  multi-tenant hosted product are outside this release.

The [demo](../src/contitext/demo.py) is an executable REST example. The MCP smoke
command checks all six tools against a real stdio server and writes synthetic
records to the explicitly configured smoke project.

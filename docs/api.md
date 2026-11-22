# API contracts

All `/v1` endpoints require `Authorization: Bearer <token>`. Token configuration
maps a credential to a principal UUID; caller-supplied metadata cannot override
that identity. Health endpoints expose readiness only and do not require a token.

| Method | Path | Access |
| --- | --- | --- |
| GET | `/v1/projects?limit=100&cursor=...` | Authenticated caller; only accessible projects |
| POST | `/v1/projects` | Provisioned caller; creates own project |
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
Reading an unbound scope produces 404. Writing with an unbound or mismatched
scope produces 409. Invalid input produces 422. Missing or invalid
bearer credentials produce 401. An unavailable projector or maintenance fence
produces 503.

## Project discovery and creation

`project_list(limit=100, cursor=None)` corresponds to `GET /v1/projects` and
returns `projects` (project_id, display_name, status, role) and `next_cursor`.
The maximum page size is 100. Follow the opaque cursor until null. Results are
ordered by project ID; revocation is checked on each page. This is not a snapshot
of a concurrently changing catalog and does not expose inaccessible projects.

`project_create(project_id, display_name)` corresponds to `POST /v1/projects`
with those two JSON fields. It creates an active project and an owner grant for
the authenticated, provisioned principal in one transaction. No scope binding is
required or changed. Requests cannot choose another owner. Each provisioned
identity can create its own projects, including an identity with no existing ACL.
This capability does not grant access to existing projects or operator commands.

IDs use ASCII letters, digits, dots, underscores, and hyphens, beginning with an
alphanumeric character (maximum 128 characters). Display names are nonblank and
at most 256 characters. A duplicate ID returns 409 with the same generic message
whether or not the existing project is visible. It is never an upsert; an
identical retry also returns 409. Unknown/unprovisioned identities cannot create.
Creation observes the maintenance writer fence; listing remains read-only.

## Context boundaries

- Every event and handoff write requires a persisted binding for the authenticated
  principal and scope that matches the requested project. Validation and insertion
  share a transaction; concurrent rebinding cannot redirect a write. Bind explicitly
  before writing, including before retrying an event after switching projects. A
  resumed conversation may use a new session ID with its existing project binding.
  Reads remain project-authorized; the agent must use its binding to select the
  correct project. The server cannot detect unsaved conversation content, so the
  agent protocol still requires a handoff before switching projects.
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
command checks all eight tools against a real stdio server and writes synthetic
records to the explicitly configured smoke project and creates one synthetic
project. Run it only in a test deployment.

## Unreleased Workspace references

The eight MCP input schemas remain unchanged. With Workspace support, `project_id`
is a reference such as `team/research`; REST project routes accept the same
qualified reference. Bare IDs require an explicit compatibility workspace.
Project membership and ACL checks apply to every project operation, including
existing bindings and exports. Lists are ordered by workspace slug, then project
slug; pagination cursors belong to the caller. Search cursors also belong to the
actual project UUID and query. See [workspaces](workspaces.md) for the migration
boundary and trusted operator model. This section applies to 0.8.0.

## Atomic automatic binding (unreleased)

`project_bind` and `PUT /v1/scopes/{scope_id}/binding` accept optional
`if_unbound: true`. The default remains manual replacement. Automatic binding
inserts only if no row exists for the authenticated principal and scope; otherwise
it returns the existing authorized binding without changing its session or time.
A revoked existing project is not replaced. Discovery clients must inspect the
MCP tool schema before using this capability and may not fall back to a blind
manual bind on older servers. No schema migration or new MCP tool is required.

# Roadmap

## v0.5: standalone foundation

PostgreSQL event storage, REST, six stdio MCP tools, explicit scope selection,
project ACLs, idempotency, lexical search, and optional Markdown projection.
Quick start, synthetic two-agent demo, portable package, and isolated tests.

## v0.6: self-hosting and migration readiness

Released project/principal/access administration,
private configuration initialization, read-only diagnostics, portable MCP client
configuration, and atomic event-to-binding consistency. See the
[self-hosting guide](self-hosting.md) for a complete operator workflow.

## v0.7: project discovery and creation

List accessible projects and create a project owned by the authenticated caller
through MCP, REST, and agent chat instructions. Simplified CLI creation resolves
the configured identity automatically. Neither operation selects a chat project.

## v0.7.1: human reading and onboarding

Read-only Markdown exports, optional periodic refresh, Obsidian setup, and an
end-to-end first-use tutorial. The database remains authoritative.

## v0.8: self-hosted release

Managed independent credentials, workspace membership and UUID namespaces,
explicit compatibility mapping, upgrade integrity checks, two-agent setup and
reader guidance are included in 0.8.0. Maintainer-run validation is recorded in
[release evidence](acceptance-0.8.md). External user feedback is welcome and is not
a prerequisite for a release.

## Before v1.0

The [v0.8.0 plan](v0.8-plan.md) records the completed self-hosting work.
The [subsequent 0.8.x plan](automation-0.8.md) covers deterministic project
resolution, nonblocking session start, bounded task-aware context assembly and
checkpoint/end automation, in that order. Versions follow validated scope rather
than a fixed feature-to-patch schedule. Explicit selection remains authoritative.

- Rehearse migration and rollback with private deployments using private tooling;
  no private project data belongs in this repository.
- Add a tested SuperLocalMemory companion example: Contitext owns project state
  and handoffs while the companion supplies broader memory retrieval. This is
  planned, not an integration shipped in v0.5.
- Improve onboarding for different MCP clients based on actual user feedback.

## Project lifecycle and repository associations

Private local mappings are available from 0.8.1; see
[project resolution](project-resolution.md). Shared repository metadata remains
a separate possible feature, independent of conversation bindings.
A project can cover several repositories, and a repository can support multiple
context projects. Associations should help discovery without inferring a default
project from a working directory. Repository moves, multiple remotes, and private
URLs require explicit update and access rules; automatic cloning or credentials
in URLs are outside the intended metadata feature.

Define archive/inactive semantics before offering lifecycle commands. The current
status field is descriptive metadata and does not revoke access or prevent writes.
Prefer reversible archival that preserves history before considering permanent
deletion, including its effects on bindings and references.

## Planned v0.9: remote MCP and hosting support

The [v0.9 Core development plan](v0.9-plan.md) proposes authenticated remote MCP,
request-scoped authorization, remote client/automation support and published OCI
images. The [hosting integration contract](hosting-integration-contract.md)
describes the generic interfaces and requirements for operators consuming Core.
These are planned capabilities, not features shipped in 0.8.4.

Self-hosters retain the complete Core product. Account sites, hosting operations
and provider-specific policy are outside this repository's development plan.
A Core release does not announce the availability of an operated service.

## Later, if users need it

Broader memory/knowledge integrations remain separate from the remote-access
milestone. No hosted availability or service-level guarantee is promised by this
Core roadmap.

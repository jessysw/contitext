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

## Before v1.0

- Add question resolution, decision supersession, and task-scoped handoff selection
  with explicit lifecycle semantics and regression tests.
- Rehearse migration and rollback with private deployments using private tooling;
  no private project data belongs in this repository.
- Add a tested SuperLocalMemory companion example: Contitext owns project state
  and handoffs while the companion supplies broader memory retrieval. This is
  planned, not an integration shipped in v0.5.
- Improve onboarding for different MCP clients based on actual user feedback.

## Project lifecycle and repository associations (not implemented)

Consider optional repository metadata independently of conversation bindings.
A project can cover several repositories, and a repository can support multiple
context projects. Associations should help discovery without inferring a default
project from a working directory. Repository moves, multiple remotes, and private
URLs require explicit update and access rules; automatic cloning or credentials
in URLs are outside the intended metadata feature.

Define archive/inactive semantics before offering lifecycle commands. The current
status field is descriptive metadata and does not revoke access or prevent writes.
Prefer reversible archival that preserves history before considering permanent
deletion, including its effects on bindings and references.

## Later, if users need it

Broader context assembly, memory/knowledge integrations, and an authenticated
remote MCP transport. A hosted service is a separate operational and security
decision; no hosted availability or service-level guarantee is promised here.

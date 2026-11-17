# Roadmap

## v0.5: standalone foundation

PostgreSQL event storage, REST, six stdio MCP tools, explicit scope selection,
project ACLs, idempotency, lexical search, and optional Markdown projection.
Quick start, synthetic two-agent demo, portable package, and isolated tests.

## Before v1.0

- Enforce event-to-binding consistency atomically in the service.
- Add question resolution, decision supersession, and task-scoped handoff selection
  with explicit lifecycle semantics and regression tests.
- Rehearse migration and rollback with private deployments using private tooling;
  no private project data belongs in this repository.
- Add a tested SuperLocalMemory companion example: Contitext owns project state
  and handoffs while the companion supplies broader memory retrieval. This is
  planned, not an integration shipped in v0.5.
- Improve onboarding for different MCP clients based on actual user feedback.

## Later, if users need it

Broader context assembly, memory/knowledge integrations, and an authenticated
remote MCP transport. A hosted service is a separate operational and security
decision; no hosted availability or service-level guarantee is promised here.

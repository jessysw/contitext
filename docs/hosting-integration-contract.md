# Hosting integration contract

Status: proposed contract `draft-0.9-1`, awaiting maintainer approval.
The 0.9 capabilities described here are not shipped in 0.8.4. This document
defines semantic responsibilities; exact new API symbols and wire formats must
be finalized and tested in the owning Core changes before consumers implement
against them. See the [Core plan](v0.9-plan.md).

## Boundary

Core provides project continuity, authorization enforcement, remote MCP,
provider-neutral operator operations and versioned artifacts. A hosting operator
provides an authorization service, account experience, admission policy,
infrastructure, quotas, monitoring, backups and customer-data lifecycle handling.
Core must also run independently for self-hosters.

Consumers install a published package or OCI image and pin the version/digest.
They must not copy Core internals, mutate Core tables directly, or implement a
second project ACL engine. Core migrations and table ownership remain in Core.
Consumer business/account records belong outside the Core schema.

## Interfaces and deliverables

| Contract | Core delivery | Consumer responsibility |
| --- | --- | --- |
| Authenticated MCP | C2: shared-service tools over tested Streamable HTTP revisions | HTTPS routing and verified host configuration |
| Identity and grants | C1/C2: verified external subject mapping, principal and scope enforcement | Configure trusted issuer/resource values and an interoperable authorization server |
| Provisioning | C1: versioned trusted Python operations for principal/workspace/owner setup | Authorize the actor, admit users, reconcile idempotent operation outcomes |
| Credential lifecycle | C1/C2: scoped issue/expiry/rotation/revocation and external-grant enforcement | Secure issuance experience, storage, connection consent and provider revocation integration |
| User data | Existing tools/REST plus C3 remote profiles and C4 authorized export | Call as the actual authorized user, not as an operator impersonating arbitrary UUIDs |
| Limits and audit | C4: generic enforcement, usage and lifecycle signals | Select policy values and supply durable enforcement configuration |
| Suspension/purge | C4: explicit actor checks, fencing and referential cleanup | Confirm the destructive intent and handle external caches, backups and retention disclosures |
| Distribution | C5/R1: tested versioned package/image, migrations and compatibility information | Pin artifacts, isolate environments, back up, promote and restore safely |

## Identity and authorization invariants

The authentication adapter derives the principal from a verified credential or
`(issuer, subject)` mapping. Neither tool `agent_id` nor a request header choosing
a principal grants authority. A third-party login token is not automatically a
Core access token; issuer and audience/resource validation are required.

Effective project access combines credential/grant restrictions, workspace
membership and project ACLs. Workspace ownership does not grant implicit read
access to all projects. Operator lifecycle permissions are separate from ordinary
data-reading permissions and require explicit documented authorization.

Use qualified `workspace/project` references in shared deployments. Existing
principal/scope bindings remain authoritative across connection changes. No
implicit project selection occurs during listing, creation or account setup.
Credential rotation must not change principal identity or redirect queued work.

Protected-resource metadata identifies the trusted authorization service.
Revocation/suspension behavior and propagation bounds must be demonstrated with
the selected integration. Do not treat signature-valid JWTs as irrevocable grants
until expiry or silently fall back to weaker authentication when verification fails.

## Operator calls and failures

The initial provisioning integration is a versioned Python interface used by a
trusted process with protected database access. It is not a public admin endpoint
and is not exposed as MCP tools. Operator inputs are validated data, never shell
fragments. Define typed inputs/results, actor authorization and transaction
boundaries before declaring these entry points stable.

Provisioning and retryable lifecycle calls use operation IDs. Identical retries
reconcile to the same result; conflicting reuse fails. Return enough bounded
status for a consumer to distinguish pending, completed, retryable failure and
permanent denial without exposing hidden tenants or secrets.

Existing MCP names, parameters and binding semantics remain compatible. HTTP
authentication failures use the protocol-appropriate 401/403 challenges; unknown
and unauthorized project access remains non-enumerating. Oversize/rate-limited
requests need documented machine-readable outcomes and retry guidance. Freeze
exact new error shapes in C2/C4 tests rather than letting consumers guess them.

## Data and artifact lifecycle

Normal exports are limited to the caller's authorized data. Portable exports
preserve the documented events/provenance required for recovery and exclude
credentials; display-only Markdown is a separate view. Operator backup is an
explicit privileged operation, not a way to bypass user export authorization.

Suspension is not deletion. Workspace purge fences new writes and defines binding,
event, reference and shared-principal handling. The consumer separately handles
issued downloads, caches, identity-provider grants and retained backups. An
account with membership elsewhere must not cause unrelated workspaces to be
deleted. These behaviors require integration tests before production use.

Record exact Core version/digest for each deployment and operator worker. An image
rollback alone is not a schema rollback. Candidate artifacts may be tested in
isolated environments; production consumers use published supported artifacts.

## Contract change process

Core owns this contract and its executable tests. Consumers report a missing
capability or ambiguous behavior as a minimal, sanitized interface proposal,
not a patch to Core internals or a dependency on undocumented SQL.

Finalize the affected contract with the corresponding Core PR, record its commit
and eventual release version, then update consumer pins and integration tests.
Keep examples synthetic and provider-neutral. No implementation or deployment
is authorized merely by adding or reviewing this document.

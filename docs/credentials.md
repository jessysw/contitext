# Managed credentials

Managed credentials are available in 0.8.0, together with workspace isolation and
the upgrade/recovery workflow. They are not included in 0.7.1. Follow the
[upgrade guide](upgrading-to-0.8.md) and rehearse against a copy before changing a
working deployment.

## Identity and trust

A credential authenticates a principal. Several credentials may refer to one
principal; use separate principals when agents need different project ACLs.
`agent_id`, agent type, machine name and conversation scope are source/context
metadata, not authentication. No new credential-management MCP tools or public
administration HTTP endpoints are exposed.

The commands below require trusted database access. A token file alone does not
grant database access or create a remote MCP transport. Continue to launch native
or SSH stdio MCP within a trusted operator environment. Do not give untrusted
users your database credentials or unrestricted server SSH access.

## Authentication modes

| Setting | Behavior |
| --- | --- |
| `CONTITEXT_AUTH_MODE=config` (default) | Existing `CONTITEXT_AUTH_TOKENS` mapping; configuration changes require restart |
| `CONTITEXT_AUTH_MODE=database` | Only database credential hashes are accepted; no fallback to configured tokens |

The migration adds credential and audit tables without editing existing project,
event, ACL, principal, binding or projection rows. It does not change the running
authentication mode or automatically import any secret.

In a disposable test deployment, migrate and import an existing protected token
configuration before switching modes:

```bash
contitext --env-file /private/path/server.env migrate
contitext --env-file /private/path/server.env credential import-config
```

Import retains principal IDs, stores hashes only, and is idempotent. Every
principal must already exist. Reimporting a revoked/expired token never reactivates
it. A token already assigned to another principal causes the entire import to fail.

Set `CONTITEXT_AUTH_MODE=database` in the private server configuration and restart
the test REST/MCP/reader processes once to select that mode. Verify access with the
existing clients. Subsequent database credential changes need no process restart.
Remove the legacy token mapping only after verifying replacement access. Merely
changing an environment variable in another shell does not change running services.

Revoking a database row cannot revoke the same secret in an independently running
config-mode process. The CLI warns about this when rotating/revoking with config
mode selected. Never switch back to an old token mapping as an access-recovery
shortcut: it may contain revoked credentials.

## Issue and inspect

Provision a principal, grant workspace membership and the intended project ACL. Issue a separately named credential for each agent installation:

```bash
contitext --env-file /private/path/server.env principal create "Second agent"
contitext --env-file /private/path/server.env credential issue PRINCIPAL_UUID \
  --name "Laptop agent" --output /private/path/laptop-agent.env \
  --expires-in 2592000
contitext --env-file /private/path/server.env credential list --principal PRINCIPAL_UUID
```

The output file contains only `CONTITEXT_MCP_TOKEN`, is created with mode `0600`,
and must not already exist (including a symlink). Its parent directory must exist
and should be private. Standard output contains metadata and the file path, never
the token or its hash. Store/transfer that file privately; do not paste it into
issues, shared agent configuration, logs or chats. No later command can retrieve
the plaintext token. Optional expiry is measured in seconds; omit it for no expiry.

When configuring a trusted MCP launch, retain its protected database configuration
and select this agent's token as `CONTITEXT_MCP_TOKEN`. Use `client-config --credential-file` to overlay this token-only file on the
shared protected configuration; see [the two-agent guide](two-agents.md). Do not
replace an entire server environment file with this token-only file. Separate client-only remote
onboarding remains part of later transport work, not this credential feature.

## Rotate and revoke

```bash
contitext --env-file /private/path/server.env credential rotate CREDENTIAL_UUID \
  --output /private/path/laptop-agent-new.env
contitext --env-file /private/path/server.env credential revoke CREDENTIAL_UUID
contitext --env-file /private/path/server.env credential audit CREDENTIAL_UUID
```

Rotation creates a new secret and revokes the old credential in one database
transaction. Without `--expires-in`, it retains the old expiry. A revoked or
expired credential cannot be rotated; issue a new one instead. Concurrent
rotations of the same credential have at most one winner. If creating/writing the
output file fails, the transaction rolls back and the old credential remains valid.

Update the selected agent's protected token configuration and restart that client
after rotation: the old token is deliberately invalid, even in its open session.
For a staged cutover, issue a second credential, verify it, then explicitly revoke
the old one. Other credentials for the same principal remain unaffected.

Database-mode authentication is checked for each HTTP request, every MCP tool
invocation, and every Markdown reader refresh. A call authenticated after a revoke
commits is rejected. A request already authenticated/in flight may finish; this
does not cancel running work or erase files previously exported. The reader marks
a failed refresh and retains a clearly stale previous copy, as with other failures.

Lifecycle audit records contain credential IDs, action and timestamp, plus the
replacement credential ID for rotation. They record trusted operator operations;
they do not identify a human operator or promise tamper resistance against a
database administrator. Audit/list output excludes secret values and hashes.

## Recovery and validation

An unused credential migration can be downgraded for a rehearsal. Once credential
history exists, downgrade refuses to discard it. Restore a verified pre-upgrade
backup into an isolated instance and validate configuration/authentication before
any real cutover; a schema rollback alone does not safely undo credential changes.

Credential tests cover independent tokens, expiry, existing-process HTTP/MCP
revocation, an actual open stdio session, reader refresh revocation, atomic and
concurrent rotation, failed secret delivery, import safety and historical data
preservation. Complete workspace isolation and final release rehearsals are still
tracked separately in the release plan.

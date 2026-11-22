# Two independently authenticated agents

This walkthrough covers 0.8.2. Start with the fresh setup in
[Getting started](getting-started.md), which owns workspace `personal`. Use one
shared database and separate principals, credentials and launchers. These are
trusted local/SSH clients, not untrusted tenants with restricted database access.

## 1. Enable managed credentials once

For Compose, import the bootstrap credential before changing modes:

```sh
docker compose exec -T app contitext credential import-config
```

Add `CONTITEXT_AUTH_MODE=database` to the private `.env`, preserving all existing
values, and recreate the service:

```sh
docker compose up -d --force-recreate --wait app
docker compose exec -T app contitext doctor
```

For native Python, run `contitext --env-file /absolute/private.env credential
import-config`, set the same mode in that protected file, and restart any REST,
reader and MCP processes. Check `doctor` using the same file. The imported
bootstrap credential still works. Remove the obsolete token mapping after that
check; database mode never falls back to it. Do not rerun `init` over existing
configuration. See [credentials](credentials.md) for rotation and recovery.

## 2. Provision Agent B and grant access

These are operator commands. Run them with your owner configuration. Substitute
the actual UUID printed by `principal create` into the following commands; find
it again with `principal list`. For the first-use tutorial the project is
`personal/first-project`:

```sh
docker compose exec -T app contitext principal create "Agent B"
docker compose exec -T app contitext workspace member grant personal PRINCIPAL_UUID
docker compose exec -T app contitext access grant personal/first-project PRINCIPAL_UUID --role writer
```

Membership permits creation in that workspace; it does not expose existing
projects. The separate project grant permits Agent B to read and write this one.
Use `reader` for read-only clients. A workspace owner still needs a project ACL.

Create a private token file on the Docker host without printing the secret or
placing it in a command argument:

```sh
mkdir -p private-clients
chmod 700 private-clients
docker compose run --rm --no-deps -T --user "$(id -u):$(id -g)" \
  --volume "$PWD/private-clients:/clients" app \
  contitext credential issue PRINCIPAL_UUID --name "Agent B" --output /clients/agent-b.env
```

The bind mount is writable even though the container root is read-only. The
file is owned by your host UID, has mode `0600`, and must not already exist.
For native Python, replace the Compose prefix with
`contitext --env-file /absolute/private.env` for the same principal/membership/ACL
commands. Issue the token directly with:

```sh
contitext --env-file /absolute/private.env credential issue PRINCIPAL_UUID \
  --name "Agent B" --output /absolute/private-clients/agent-b.env
contitext --env-file /absolute/private.env \
  --env-file /absolute/private-clients/agent-b.env doctor
```

The token-only file overrides the bootstrap token. It does not replace database
configuration, grant SSH access or create a project binding.

## 3. Install Agent B's own connection

For Compose, first confirm `docker compose run --help` lists `--env-from-file`.
This allows the host CLI to read a private file without relaxing its permissions:

```sh
docker compose exec -T app contitext client-config --compose "$PWD" \
  --credential-file "$PWD/private-clients/agent-b.env" > client-b.json
```

Add `--compose-project NAME` if you started the stack with `-p NAME`.
For native Python:

```sh
contitext client-config --config-file /absolute/private.env \
  --executable /absolute/venv/bin/contitext \
  --credential-file /absolute/private-clients/agent-b.env > client-b.json
```

Both forms support `--ssh context-host`; all referenced paths then belong to
that server. Run the installer on the client machine with the generated JSON.
For example, keep Agent A in Codex and configure Agent B in Claude:

```sh
sh scripts/install-agent-adapters.sh --config client-b.json --target claude --dry-run
sh scripts/install-agent-adapters.sh --config client-b.json --target claude
```

Use the corresponding target for Zed, Hermes or OpenClaw instead. Different
machines can use the same target with different connection files. Installing a
second client on one machine leaves the first client's launcher intact. To use
two profiles of the same client on one machine, configure their isolated homes
explicitly; one target in one home has one managed connection.

Reload MCP. In Agent B, send each instruction separately:

```text
!! contitext list
!! contitext use personal/first-project
!! contitext status
```

Expected: the handoff written by Agent A is visible, including its next action.
Agent B has its own binding even if its scope string matches Agent A's. The
service may return the configured short alias `first-project`; it still resolves
to the same UUID. No conversation is bound merely by installation or creation.

## Diagnose and revoke

Run `doctor` with the affected client's token overlay, not just the operator
credential. It distinguishes schema, credential, membership, short-ID resolution
and project-access checks. An empty project list is valid: a workspace member
can create a project or request a grant. No-access and nonexistent project reads
both return not-found to avoid disclosing another workspace's data.

Use `workspace member revoke personal PRINCIPAL_UUID` to remove all access to
that workspace, or `access revoke personal/first-project PRINCIPAL_UUID` for just
one project. Membership removal retains stored ACLs; explicitly restoring that
membership restores those grants. `credential list --principal PRINCIPAL_UUID`
shows credential IDs; `credential revoke CREDENTIAL_UUID` disables that token.
In database mode, the next call fails even in an open MCP session. An operation
already authorized may finish. Other identities remain connected.

The [reader](obsidian.md) can use a dedicated token overlay too. A successful
all-project refresh removes pages no longer authorized; failed authentication
retains a marked stale copy. Files already copied elsewhere cannot be recalled.

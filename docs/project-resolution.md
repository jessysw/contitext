# Project resolution

Available in 0.8.1.
It is opt-in. Existing installations continue to use explicit chat selection.
The commands below are terminal commands; they are not additional chat commands.

## Configure one trusted connection

Use an existing MCP connection produced by `contitext client-config`. A native
example, after following the [first-use tutorial](getting-started.md):

```sh
mkdir -p "$HOME/.config/contitext"
chmod 700 "$HOME/.config/contitext"
contitext client-config --config-file /absolute/private/server.env \
  --executable /absolute/venv/bin/contitext \
  > "$HOME/.config/contitext/client.json"
chmod 600 "$HOME/.config/contitext/client.json"
```

Docker and SSH connection output works the same way. The client needs the
Contitext Python package and access to the command in that JSON; it does not need
its own PostgreSQL connection. Keep secrets in the private server/credential
files. The JSON accepts only `command` and `args`, optionally wrapped in
`{"mcpServers":{"contitext":...}}`. Review that executable and its arguments:
this is trusted operator configuration, not something to accept from a repository.

## Add explicit mappings

Obtain the qualified project reference from the workspace operator, or list
accessible projects. A bare slug is intentionally insufficient for a mapping.
Creating a mapping neither creates a project nor selects the current conversation.

```sh
contitext mapping add \
  --connection "$HOME/.config/contitext/client.json" \
  --mappings "$HOME/.config/contitext/projects.json" \
  --remote https://github.com/example/sample-app.git --project personal/sample

# Optional directory fallback; the directory must already exist.
contitext mapping add \
  --connection "$HOME/.config/contitext/client.json" \
  --mappings "$HOME/.config/contitext/projects.json" \
  --directory /absolute/projects/sample-app --project personal/sample

contitext mapping list \
  --connection "$HOME/.config/contitext/client.json" \
  --mappings "$HOME/.config/contitext/projects.json"
```

Files are private (0600); their directory must be caller-owned and not writable
by other users. Files with unsafe permissions, symlinks or duplicate selectors
are rejected. Repeating an identical mapping is harmless; replacing its target
requires explicit `mapping remove` with the same connection, file and selector,
then `mapping add`. Removal also works after a mapped directory has moved.

## Preview, then opt in to binding

Use the actual stable conversation and session identifiers supplied by the
runtime. Do not invent a fresh scope every time the command runs.

```sh
contitext resolve \
  --connection "$HOME/.config/contitext/client.json" \
  --mappings "$HOME/.config/contitext/projects.json" \
  --cwd /absolute/projects/sample-app \
  --scope-id example-client:conversation-123 --session-id session-123
```

The default is a read-only authorization-checked preview. Add `--bind` to establish
an unbound scope. JSON reports `bound`, `matched`, `unmatched` or `ambiguous`.
Unmatched/ambiguous exits 1; configuration or connection failure exits 2.
`--timeout` bounds connection and resolution (default 5 seconds, range 0.1–30).
An older server without `project_bind(if_unbound=...)` can preview, but cannot
perform automatic binding. Upgrade it or continue using explicit chat selection.

Selection order:

1. Existing authorized conversation binding, including a prior explicit
   `!! contitext use`. It wins without consulting local mappings.
2. One uniquely mapped full Git remote identity from the local repository.
3. The most specific configured ancestor directory, if no remote matched.
4. No match: remain unbound and use the existing explicit selection workflow.

Matching remotes for different projects are ambiguous; directory fallback must
not hide that conflict. Multiple remotes for the same project are acceptable.
The server atomically preserves a concurrent manual binding, including its session
and timestamp. Revoked access cannot be bypassed by replacing an existing binding.

## Identity and limitations

HTTPS and normal Git SSH spellings share an identity, including the full host,
owner and repository path. Nondefault ports remain distinct. Paths are case
sensitive; a repository basename alone never matches. Credentials, query strings,
local-file remotes and URL-encoded paths are rejected. Git aliases (`insteadOf`)
and SSH aliases are not expanded; map an accepted exact identity or use an
explicit directory mapping. No network fetch, clone or hook execution occurs.
Directory paths are absolute and canonicalized when added; matching observes
path-component boundaries, not string prefixes. Nested directories can have
more specific mappings. Symlink aliases resolve to their real directory.

A mapping file is tied to the command/args fingerprint of one connection. Changing
the connection requires reviewing and rebuilding mappings; do not edit its hash
to bypass the check. This prevents accidental cross-deployment reuse, not a
malicious operator changing an executable or server configuration behind a path.
Mappings are local associations, not shared project metadata or access grants.
Repository-local configuration is never automatically discovered or trusted.

For automatic loading at startup, see [session start hooks](session-hooks.md).

# Obsidian and the Markdown reader

Contitext can export a human-readable copy of project state and history.
Open it in Obsidian or any Markdown reader without asking an agent. The exporter
needs no Obsidian API, plugin, subscription, or LLM. Obsidian is optional.

The data flow is one way:

```text
PostgreSQL → authenticated Markdown export → optional file transfer → local reader
```

## What you can see

- An index of projects accessible to the configured identity, with status and role.
- The latest recorded checkpoint and handoff for each project.
- Complete recorded decision, question, note, checkpoint, and handoff history.
- Event timestamps, agent attribution, and source identifiers.
- The last successful database snapshot and the result of the latest refresh.

Payloads are rendered as readable fields and lists. Explicit Markdown link and
embed syntax and stored HTML are escaped. A reader such as Obsidian can still
auto-link a plain URL; this does not load an embedded image or execute HTML. A question is not automatically resolved
by a later event; decisions are not automatically superseded. Those are existing
context lifecycle limits, not deductions made by the reader.

## Docker Compose

After the [getting-started setup](getting-started.md), run:

```sh
mkdir -p reader-vault
docker compose --profile reader up --build -d --wait
```

The optional reader builds from the same source as the app, reads the same
database, and refreshes the host's `reader-vault` folder every 60 seconds. It has
an automatic restart policy and a health check for snapshot freshness. Normal
`docker compose up` does not enable the reader profile.

Fresh bootstrap configuration records your host UID and GID. **For an older
`.env`, or a deployment moved to another host**, set those values before creating
or recreating the reader:

```sh
mkdir -p reader-vault
export CONTITEXT_READER_UID="$(id -u)"
export CONTITEXT_READER_GID="$(id -g)"
docker compose --profile reader up --build -d --wait
```

Run with the same values on subsequent recreations, or save the numeric values
under those two keys in the private `.env`. These are operating-system file
owners, not Contitext principal UUIDs. Do not regenerate `.env` to add them.
The reader container mounts only the generated folder. It has no published port.

Inspect status with:

```sh
docker compose --profile reader ps
docker compose --profile reader logs --tail 30 reader
```

Stop only the reader with `docker compose --profile reader stop reader`.
Your app and database can continue running.

## Native Python

Use the same protected configuration as the service. The configured MCP identity
must have workspace membership and at least reader access to the projects you
want to export. Add a second `--env-file /absolute/reader-token.env` before
`export` to use a dedicated managed credential:

```sh
contitext --env-file /absolute/private.env export --output /absolute/reader-vault
```

This creates one snapshot and exits. The parent directory must already exist.
For continuous refresh:

```sh
contitext --env-file /absolute/private.env export \
  --output /absolute/reader-vault --watch 60
```

Run the watcher under your normal process supervisor if it should survive logout
or reboot. A foreground command stops with the terminal. Each iteration prints a
small JSON status without credentials. Failed refreshes retry at the next interval;
one-shot failures exit nonzero. The minimum interval is 10 seconds.

Default selection is all projects the identity can currently access, including
new projects created later. To choose projects explicitly, repeat `--project`:

```sh
contitext --env-file /absolute/private.env export --output /absolute/reader-vault \
  --project personal/research --project team/documentation --watch 60
```

No owner UUID or conversation binding is needed. Export reads membership, ACLs and events in
a consistent read-only transaction. It does not change events, bindings, or
legacy projection offsets. Export requires trusted database connectivity plus
the configured token; it is not a new public HTTP or MCP endpoint.

## Open the folder in Obsidian

1. Open Obsidian's vault switcher / **Manage vaults**.
2. Choose **Open folder as vault** and select the generated reading folder.
3. Open `README.md` and follow a project link.
4. Open `SYNC-STATUS.md` to check freshness or a reported failure.

Obsidian refreshes notes when external files change. See the official
[vault instructions](https://help.obsidian.md/Files+and+folders/Manage+vaults) and
[data storage explanation](https://help.obsidian.md/Files+and+folders/How+Obsidian+stores+data).

Use a **new, dedicated folder**, not an existing personal vault, source checkout,
or old curated context folder. Contitext refuses unrelated nonempty directories,
symlinks, concurrent exporters, and folders assigned to another identity. Obsidian's
`.obsidian` settings are preserved. Generated project filenames contain a qualified namespace and
a short stable digest to avoid case-insensitive filename collisions; use the index
for human-readable project names.

## Service on another machine

The exporter writes files on the service host. Opening a different local folder
does not connect it to that host. First run the exporter there, then transfer its
generated files over an existing trusted SSH connection. For example, after
substituting your real SSH alias and absolute server path:

```sh
mkdir -p "$HOME/Contitext Reader"
rsync -az --delay-updates --delete-after \
  --exclude='.obsidian/' --exclude='.contitext-reader.lock' \
  context-host:/absolute/reader-vault/ "$HOME/Contitext Reader/"
```

The trailing slashes are intentional. Use a dedicated generated destination:
`--delete-after` removes local files absent from the source. It preserves the
excluded Obsidian settings. Never aim this command at a personal notes folder.
Run the transfer again to refresh, or schedule it with your operating system's
job scheduler. Enable both the server exporter and the local transfer after login
if you want unattended updates. Keep source and transfer timestamps visible.

This command is a one-time transfer, not an installed cross-platform sync service.
A local export needs no transfer. The reader remains usable with other file
transfer tools if they preserve the one-way direction and private access.

## Ownership, freshness, and limitations

- PostgreSQL is authoritative. Editing generated pages does not write back to it;
  refresh replaces those edits. Keep personal notes outside this generated folder.
- Each file is replaced atomically, and the manifest tracks pending refreshes.
  A failed multi-file refresh may leave a mixture of old and new pages;
  `SYNC-STATUS.md` and the completion timestamp show whether it finished.
- A stopped or killed process cannot report its own failure. An old timestamp
  means the copy may be stale even when the last recorded result was OK.
- A successful full refresh removes previously generated pages for revoked or
  deleted projects. A failed refresh retains prior files. Already downloaded
  copies and separately copied content cannot be recalled by revoking membership, an ACL or a credential. Token rejection fails the whole
  refresh and retains a marked stale copy; a successful all-project refresh after
  membership/ACL removal omits the now-inaccessible projects.
- The exporter reads complete event history. Large deployments should select
  projects or increase the interval rather than treating this as an incremental
  database replication system.
- This reading copy does not include arbitrary curated Markdown that was never
  recorded in the database. Keep those documents separately. The older owner-only
  REST projection into curated files remains available and unchanged.
- The reader requires the matching server schema. No Obsidian plugin, hosted
  service or bidirectional editing protocol is introduced.

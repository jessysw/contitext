# MCP Registry setup

Contitext's official MCP Registry name is `io.github.jessysw/contitext`. Its
`server.json` describes release 0.8.3. Its version-pinned PyPI stdio
launcher is:

```sh
uvx --python 3.12 contitext==0.8.3 mcp
```

The package supports standard CPython 3.11–3.14. The Registry launcher pins
Python 3.12 for a reproducible default; native installations can use any supported
version.

The Registry is a directory of server metadata. It does not host Contitext or
provide a database, account, or credentials. Each deployment retains its own
project data. This release exposes MCP over stdio; the REST API is not a remote
MCP endpoint.

Version 0.7.1 uses config-mode credentials. The workspace and database-mode
settings below require 0.8.1 or later. Pin the launcher to the version deployed
by your operator.

## Prepare your deployment

Choose either path in the [installation guide](installation.md). For native use,
`contitext init --project YOUR_PROJECT` generates private configuration and an
initial owner grant; apply `contitext migrate` and `contitext admin seed --if-empty`
with that configuration. These are administrator operations performed before
starting the MCP client. The Registry launcher itself does not create a database
or seed a default project.

If you already use the Docker Compose quick start, use the Docker command in the
[README](../README.md) to share that deployment. Its PostgreSQL service is private
to the Compose network; a host-side `uvx` process cannot connect to the Compose
hostname `postgres`. Do not expose that database publicly just to use the Registry.

For a native deployment, install `uv` and make the following values available to
the MCP process through your client's secure configuration:

| Variable | Required value |
| --- | --- |
| `DATABASE_URL` | Your reachable, migrated PostgreSQL database URL using `postgresql+psycopg://` |
| `CONTITEXT_AUTH_TOKENS` | A JSON object mapping your generated credentials to `principal_id` and `name` values, matching seeded principals |
| `CONTITEXT_MCP_TOKEN` | This client's credential from the selected authentication mode |
| `CONTITEXT_AUTH_MODE` | `config` (default) or `database`; the JSON token map is required only in config mode |
| `CONTITEXT_COMPATIBILITY_WORKSPACE` | Optional explicit workspace for short IDs; otherwise use `workspace/project` |

The URL and client token are required secrets. The legacy JSON map is a
conditional secret; mode and compatibility namespace are optional non-secret
settings. No live values
are published. Generate your own credentials; never commit them to a repository
or paste them into a public issue. Database access is a trusted administrator
capability. Provide each client only the credential entries it needs and grant
its principal the appropriate project ACLs.

## Connect your client

Clients that consume the Registry can read the package, runtime arguments, and
required inputs from `server.json`. For a manual configuration, the equivalent
command is:

```json
{
  "mcpServers": {
    "contitext": {
      "command": "uvx",
      "args": ["--python", "3.12", "contitext==0.8.3", "mcp"]
    }
  }
}
```

Supply the applicable environment variables through your client's configuration or
environment inheritance mechanism. Formats differ between clients. An empty
environment will not work, and registration does not automatically install or
configure the server in every client.

If a manual client can access a native installation's protected configuration file,
its command may instead be `uvx --python 3.12 contitext==0.8.3 --env-file
/absolute/private.env mcp`. This explicitly loads the private configuration; it does not change the Registry
manifest's inputs.

Load the [agent protocol](../integrations/PROJECT-CONTEXT-PROTOCOL.md) into your
client's instruction mechanism, then restart its MCP session. In agent chat, use
`contitext: use <your-project-id>` to select an explicitly seeded project.
`contitext:` is the only chat prefix. Terminal commands begin
with `contitext`, without the chat colon.

See [release instructions](releasing.md) for publishing updates to the Registry.

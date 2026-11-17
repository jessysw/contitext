# MCP Registry setup

Contitext's official MCP Registry name is `io.github.jessysw/contitext`. Its
`server.json` describes a versioned PyPI package running over stdio:

```sh
uvx --python 3.12 contitext==0.5.3 mcp
```

The Registry is a directory of server metadata. It does not host Contitext or
provide a database, account, or credentials. Each deployment retains its own
project data. This release exposes MCP over stdio; the REST API is not a remote
MCP endpoint.

## Prepare your deployment

Use the [installation guide](installation.md) to configure PostgreSQL 16+, apply
`contitext migrate`, and run `contitext admin seed` with your projects, principals,
and project ACLs. These are administrator operations performed before starting
the MCP client. The launcher does not create a database or seed a default project.

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
| `CONTITEXT_MCP_TOKEN` | The credential from that object to use for this client |

All three are marked secret and required in the Registry manifest. No live values
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
      "args": ["--python", "3.12", "contitext==0.5.3", "mcp"]
    }
  }
}
```

Supply the three environment variables through your client's configuration or
environment inheritance mechanism. Formats differ between clients. An empty
environment will not work, and registration does not automatically install or
configure the server in every client.

Load the [agent protocol](../integrations/PROJECT-CONTEXT-PROTOCOL.md) into your
client's instruction mechanism, then restart its MCP session. In agent chat, use
`!! contitext use <your-project-id>` to select an explicitly seeded project.
`!! ctx` is a shortcut and `!! context` is a legacy alias. Terminal commands begin
with `contitext`, without exclamation marks.

See [release instructions](releasing.md) for publishing updates to the Registry.

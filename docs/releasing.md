# Releasing

The first PyPI upload must contain the working package. An empty name-reservation
package is not a release. Check name availability immediately before publishing.

Use [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
with a pending publisher for the first release. Configure:

| Field | Value |
| --- | --- |
| PyPI project | `contitext` |
| GitHub owner | `jessysw` |
| Repository | `contitext` |
| Workflow filename | `publish.yml` |
| GitHub environment | `pypi` |

The account owner must configure and authorize the PyPI publisher. This repository
contains no PyPI API token. Creating a pending publisher is not a guarantee that a
name has been reserved: the project is created by its first successful upload.

Keep the version in `pyproject.toml`, `src/contitext/__init__.py`, the REST API,
`server.json` (both the server and package versions), and installation examples
in sync. The README must retain its `mcp-name: io.github.jessysw/contitext` ownership
marker so it is included in the published PyPI description.

After CI passes, create a matching version tag (for example, `v0.5.3`). Manually
dispatch the **Publish release** workflow (`publish.yml`) from that tag. It tests
and builds without publishing credentials, then hands the distributions to a
separate PyPI publishing job using OIDC. Once PyPI succeeds, another job verifies
the published ownership marker and publishes `server.json` to the MCP Registry
using GitHub OIDC. It does not run on every commit or release.
Use English for the commit, release title, and release notes.
Verify the resulting version on PyPI and install it in an empty environment before
advertising the package as available. Add appropriate environment approvals for
the repository's maintainers as the project grows.

## MCP Registry

The namespace `io.github.jessysw/contitext` is authenticated by the GitHub repository
owner. No Registry account, personal access token, or additional publishing secret
is required for the OIDC workflow. The publisher binary is version-pinned and its
Sigstore signature is verified before execution.

The Registry entry describes the PyPI package and stdio command, not a hosted
service. See [client setup](mcp-registry.md) for required configuration.

If Registry publication fails after PyPI succeeds, fix the reported problem and
use **Re-run failed jobs** when the existing tagged workflow can safely be retried.
Do not dispatch the entire workflow again: PyPI does not allow replacing an
existing distribution. A source or workflow correction needs a new tested version
and tag. Confirm the exact server name, version, and package in the
[Registry API](https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.jessysw%2Fcontitext)
after publication.

Official references: [GitHub Actions publishing](https://modelcontextprotocol.io/registry/github-actions)
and [PyPI ownership verification](https://modelcontextprotocol.io/registry/package-types).

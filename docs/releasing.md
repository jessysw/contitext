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

The API takes its version from the package. Documentation tests compare current
install pins and the README tool table with package/Registry metadata and MCP
definitions. Keep historical changelog entries unchanged. Rehearse the
getting-started path and optional reader in a disposable deployment before
publishing changes to onboarding; never use a production database for tests.

After CI passes, create a matching version tag (for example, `v0.8.0`). Manually
dispatch the **Publish release** workflow (`publish.yml`) from that tag. It tests
and builds on Python 3.11–3.14 without publishing credentials. All four jobs must
pass before the Python 3.12 distributions are handed to a separate PyPI publishing
job using OIDC. Once PyPI succeeds, another job verifies
the published ownership marker and publishes `server.json` to the MCP Registry
using GitHub OIDC. A final job opens the Homebrew formula update PR.
These publishing jobs do not run on every commit or release.
Before dispatch, configure `HOMEBREW_TAP_TOKEN` as described in the
[Homebrew release guide](homebrew.md#release-automation-and-verification).
The preflight rejects a missing token before uploading to PyPI.
Use English for the commit, release title, and release notes.
Verify the resulting version on PyPI and install it in an empty environment before
advertising the package as available. Add appropriate environment approvals for
the repository's maintainers as the project grows.

## Maintainer release acceptance

Normal releases use `MAJOR.MINOR.PATCH` versions such as `0.8.0` and `0.8.1`.
A prerelease is optional when there is a specific reason to distribute unfinished
work; it is not a required stage. A solo maintainer may review and merge a focused
release PR once its checks pass. A separate review team or minimum number of
external testers is not required.

Before publishing:

1. Review the complete change and resolve known release-blocking defects.
2. Pass the full compatibility CI, installed-wheel/Compose checks, documentation
   consistency tests, package builds and distribution validation.
3. Record relevant first-use, upgrade and recovery rehearsals. Existing evidence
   may be reused when the release does not change the exercised runtime behavior;
   the release commit must still pass CI and package checks.
4. Align version metadata, installation examples, changelog and upgrade guidance.
5. Merge the PR, tag that exact commit and run the publishing workflow above.
6. Verify PyPI and the MCP Registry, confirm the Homebrew update PR passes and
   merges, install the published package, then create a
   non-prerelease GitHub Release and mark it Latest. Confirm the default public
   versions and close the release tracker.

See [recorded validation](acceptance-0.8.md). Maintainer and automated tests are
not independent user testing; describe the evidence accurately. External feedback
is welcome after release and informs fixes, but does not block publication or
promotion. Never overwrite an uploaded artifact, rewrite a published tag, or
claim a live deployment was upgraded merely because a release was published.

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

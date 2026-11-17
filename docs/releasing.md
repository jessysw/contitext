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

After CI passes, create a version tag matching `pyproject.toml` (for example,
`v0.5.0`). Manually dispatch the **Publish to PyPI** workflow from that tag. It tests
and builds without publishing credentials, then hands the distributions to a
separate publishing job using OIDC. It does not run on every commit or release.
Verify the resulting version on PyPI and install it in an empty environment before
advertising the package as available. Add appropriate environment approvals for
the repository's maintainers as the project grows.

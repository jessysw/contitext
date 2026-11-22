# Security

Contitext is intended for trusted, self-hosted use. Report vulnerabilities
privately through the repository's GitHub security advisory reporting feature.
Do not include tokens, database dumps, personal conversations, or project secrets
in public issues. If private reporting is unavailable, open an issue requesting a
private contact without disclosing exploit details.

Bearer credentials authorize a server-side principal. Project reader/writer/owner
ACLs are checked for REST and MCP calls. Database credentials, Docker access, and
the seed administrator are trusted administrative capabilities. This release has
no OAuth authorization server, browser login, encryption at rest, or hosted-tenant
management. In configuration authentication mode, rotate tokens through configuration
and restart affected processes. Use TLS for HTTP access outside localhost.

Version 0.8.0 includes opt-in [database credentials](docs/credentials.md)
with expiry and per-request revocation checks. Configuration authentication remains
the default; switching modes is explicit. Database revocation does not remove
tokens from old configuration-mode processes. Already authenticated in-flight work
may complete. Credential audit records identify trusted operator actions, not a
human actor, and are not tamper-proof against database administrators.

Store credentials and backups outside Git. Events can contain sensitive project
content; they are not automatically redacted. Scope selection and lifecycle limits
are documented in [API contracts](docs/api.md). Review them before enabling clients.

The project is supported on a best-effort basis; security fixes will
target the latest release. Do not assume older versions receive backports.

Markdown reader exports contain authorized project content in local files. Protect
that folder like a backup. ACL revocation prevents future database reads, but
cannot recall copies already downloaded. Generated pages escape stored HTML and explicit
Markdown link/embed syntax. Readers may still auto-link plain URLs. Obsidian
community plugins are not required.

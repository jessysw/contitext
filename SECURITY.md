# Security

Contitext is intended for trusted, self-hosted use. Report vulnerabilities
privately through the repository's GitHub security advisory reporting feature.
Do not include tokens, database dumps, personal conversations, or project secrets
in public issues. If private reporting is unavailable, open an issue requesting a
private contact without disclosing exploit details.

Bearer credentials authorize a server-side principal. Project reader/writer/owner
ACLs are checked for REST and MCP calls. Database credentials, Docker access, and
the seed administrator are trusted administrative capabilities. This release has
no OAuth authorization server, browser login, per-token expiry, encryption at rest,
or hosted-tenant management. Rotate tokens through configuration and restart
affected processes. Use TLS for HTTP access outside localhost.

Store credentials and backups outside Git. Events can contain sensitive project
content; they are not automatically redacted. Scope selection and lifecycle limits
are documented in [API contracts](docs/api.md). Review them before enabling clients.

The project is supported on a best-effort basis; security fixes will
target the latest release. Do not assume older versions receive backports.

Markdown reader exports contain authorized project content in local files. Protect
that folder like a backup. ACL revocation prevents future database reads, but
cannot recall copies already downloaded. Generated pages escape stored HTML,
links, and embeds; Obsidian community plugins are not required.

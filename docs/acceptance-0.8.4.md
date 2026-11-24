# 0.8.4 release acceptance

This release adds Homebrew distribution and stable package paths for generated
hooks/plugins. It changes no database schema, MCP tool, ACL, project/session
binding or chat-command contract. Public publication and private deployment
upgrades remain separate operations.

## Evidence and boundaries

- Local CPython 3.13 and a disposable PostgreSQL 18 database: **326 tests passed**.
  Wheel/sdist metadata and contents passed distribution validation and Twine checks.
- The implementation CI covers Python 3.11–3.14, PostgreSQL 16 and 18, selected
  dependency floors, installed-wheel operation and clean Docker Compose startup.
- The formula generator resolves four macOS/Linux architecture targets for
  Python 3.14 and pins source artifacts and their SHA256 hashes. It replaces the
  bundled Psycopg driver with the matching C driver linked to Homebrew libpq.
- Native acceptance uses isolated UTF-8 PostgreSQL, synthetic projects and fresh
  private configurations. No maintainer production database is used.
- Installation invokes real stdio MCP initialization, all eight tools, durable
  writes/reads and a handoff. Each of the eight adapter contracts loads context,
  writes a candidate and verifies idempotent retry through an actual connection.
- Candidate upgrade tests install the public 0.8.3 baseline, initialize data and
  a stable client configuration, upgrade to the source artifact, remove the old
  keg and compare complete database snapshots and private files. Newly generated
  hook/plugin commands must use the verified Homebrew `opt` Python path.
- Uninstall tests retain private configuration/client files and context records.
  The formula has no service block or post-install database/agent mutation.

These are installed-package and adapter tests. They are not new authenticated
chat demonstrations inside eight host applications. The
[0.8.3 native-host evidence and limitations](acceptance-0.8.3.md) remain applicable
and are not replaced by fixture or bridge results.

## Native platform evidence

| Platform | Clean installation / MCP / uninstall | Upgrade from 0.8.3 / data preservation | Scope |
| --- | --- | --- | --- |
| Apple Silicon macOS | Passed | Passed | Native Homebrew source installation |
| x86-64 Linux | Passed | Passed | Native Homebrew source installation |
| Intel macOS | Incomplete | Incomplete | Stopped while compiling upstream Homebrew dependencies; use Python installation |
| ARM64 Linux | Not exercised | Not exercised | Dependency resolution only |

The [tap rehearsal](https://github.com/jessysw/homebrew-tap/actions/runs/45363732251)
and [candidate rehearsal](https://github.com/jessysw/contitext/actions/runs/45363935371)
completed their Apple Silicon and x86-64 Linux jobs successfully. Their Intel jobs
were cancelled after logs showed prolonged upstream dependency builds, before
Contitext installation. This is not an Intel pass. Homebrew no longer supplies new
Intel bottles; see its [support tiers](https://docs.brew.sh/Support-Tiers).
Current release gates cover Apple Silicon macOS and x86-64 Linux.

## Operational notes

The tap currently builds from source. First builds can take ten minutes or more
and require Homebrew's build dependencies; this is not a prebuilt bottle release.
Use PyPI or Docker if those installation paths better match your environment.

The first tap CI found an obsolete Homebrew assertion spelling. A later native
rehearsal exposed SQL_ASCII in the disposable database initialization; it was
reproduced and corrected by explicitly selecting UTF-8. Neither issue was hidden
by skipping the failing checks.

A scoped release token is required to open cross-repository formula update PRs.
The default source-repository token is insufficient. Formula PRs must pass their
native platform workflow before the guarded merge job can merge them. Same-version
reruns do not regenerate published dependencies, and automated downgrades are
rejected. Failed publication stages must be retried without overwriting PyPI
artifacts or released tags.

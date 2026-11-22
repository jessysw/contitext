# 0.8.2 release acceptance

This release extends the 0.8.1 automation foundation to additional clients. Evidence
below is maintainer and automated validation, not independent user testing or a
claim that every authenticated agent GUI was exercised.

## Deliveries

| Delivery | Pull request | Validation |
| --- | --- | --- |
| MCP and instructions for Copilot, Cursor, OpenCode and Gemini | [#21](https://github.com/jessysw/contitext/pull/21) | 198 local tests; seven CI jobs passed |
| Native command-hook contracts | [#22](https://github.com/jessysw/contitext/pull/22) | 205 local tests; seven CI jobs passed |
| Native Hermes, OpenClaw and OpenCode 2 adapters | [#23](https://github.com/jessysw/contitext/pull/23) | 215 local tests; seven CI jobs passed |
| Diagnostics, safe disabling and artifact acceptance | [#24](https://github.com/jessysw/contitext/pull/24) | 225 local tests; seven CI jobs passed |

The release-preparation PR reruns the complete matrix on the aligned stable source.
[Tracker #20](https://github.com/jessysw/contitext/issues/20) records final checks,
published artifact hashes and GitHub/PyPI/MCP Registry results.

## Release gates

- Python 3.11–3.14, the dependency compatibility floor, PostgreSQL 16 and 18.
- Installed wheel outside the checkout: fresh workspace/project, migrations,
  initialization, authenticated MCP handoff/read and Markdown reader export.
- Fresh Docker source artifact: isolated bootstrap, real MCP write/read, restart,
  reader, loopback app binding, no PostgreSQL host port and no administrative HTTP routes.
- Both installed paths run all eight automation bridges: configured startup,
  candidate checkpoint, idempotent replay and MCP readback. Command clients also
  exercise read-only diagnostics and generated-hook removal.
- Node.js 24 executes exported JavaScript lifecycle fixtures in every test job.
  Native event shapes, existing bindings, compression lineage, bounded outages,
  output limits and private state/export handling are covered.
- Wheel/sdist source equality, archive privacy, English documentation links,
  version metadata, install pins and Registry ownership marker are checked.
- Source scans inspect private identities, internal hosts/paths and token/key
  patterns. Synthetic redaction fixtures are identified separately from secrets.

See [runtime evidence and limitations](hook-diagnostics.md#verification-coverage).
Bridge and contract tests do not establish runtime trust, authenticated UI behavior,
or recovery of a response that the host never emitted. Automatic progress remains
an unconfirmed candidate; it is never silently promoted to a decision or handoff.

The schema is unchanged from 0.8.1. Existing 0.8.1 migration/integrity evidence is
retained; this release repeats its regression suite rather than inventing a new
migration. Public release and private service upgrades are separate operations.

## Local stable-artifact rehearsal

On 2026-11-22, the final aligned source passed 225 tests with CPython 3.13 and
PostgreSQL 18. The built wheel installed into an independent environment outside
the checkout. All eight bridges completed startup, candidate write/read and
idempotent replay against native MCP and a disposable Docker service. The local
Docker diagnostic image reused cached dependencies; pristine source-artifact
build, initialization, restart and reader acceptance are covered separately by CI.
Default port and administrative-route checks passed in the disposable deployment.

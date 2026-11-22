# 0.8.1 release acceptance

This report records maintainer and automated validation, not independent user or
GUI acceptance. Production services and live agent configurations were not changed.

## Functional deliveries

| Delivery | Evidence |
| --- | --- |
| Project resolution | PR #15; 172 local tests; all seven CI jobs passed; merge `2302fe8` |
| Session start | PR #16; 178 local tests; all seven CI jobs passed; merge `b90d974` |
| Context assembly | PR #17; 185 local tests; all seven CI jobs passed; merge `87c92f9` |
| Candidate checkpoints | PR #18; 193 final CI tests across the full matrix; all seven jobs passed; merge `4f819c6` |

The release-preparation PR reruns the complete compatibility matrix at the exact
release head. See [tracker #14](https://github.com/jessysw/contitext/issues/14) for
final check runs, publication links and hashes.

## Release gates

- Full tests: Python 3.11–3.14, dependency-floor job, PostgreSQL 16 and 18.
- Fresh native wheel: initialize a disposable workspace/project, migrations,
  doctor, actual MCP handoff/read and reader export outside the source checkout.
- Fresh Docker source artifact: unmodified Dockerfile/Compose, isolated database,
  bootstrap, MCP handoff/read, restart and optional reader.
- Both installed paths: actual local hook client resolves a configured project,
  loads assembled context, captures a candidate, retries idempotently and reads
  the candidate through MCP. Runtime-shaped fixtures verify the hook contract;
  no real client trust bypass or GUI automation is used.
- Upgrade: seed the actual 0.8.0 schema, compare event/binding/ACL/credential
  fingerprints after migration, and refuse a downgrade that discards metadata.
- Security: full authorization/binding tests, private file/symlink checks,
  candidate redaction, timeout/process cleanup, stale-binding replay rejection,
  default loopback app binding and no PostgreSQL host port or admin HTTP routes.
- Distribution: matching version metadata, documentation links, wheel/sdist,
  Twine and artifact privacy/migration checks.

The release PR and CI are the authoritative final results for these gates.
Native hooks cover Codex and Claude Code on macOS/Linux. Hermes, OpenClaw, Zed and
other MCP clients retain explicit commands. Token budgeting uses documented compact
JSON byte accounting; it is not an exact model tokenizer. Exit/interruption can
retry captured work but cannot recover progress never provided by the runtime.

## Local release rehearsal

On 2026-11-22, the aligned 0.8.1 source passed 194 tests with CPython 3.13 and
PostgreSQL 18. A fresh environment then installed the built wheel with its 39
runtime dependencies, outside the checkout, against a new empty test database.
Initialization, migration, seed, doctor, real MCP handoff/read, Markdown export,
session-start assembly and idempotent candidate checkpoint/read all passed.
The final isolated-import regression passed with a repository-shadowed package
and hostile `PYTHONPATH`; the rebuilt wheel also passed actual MCP hook acceptance.

The installed-artifact script is `scripts/check_hook_installation.py`; CI runs it
against both the native wheel and fresh Docker source artifact. Distribution
checks inspect exact wheel source and archive contents. The source privacy scan
found only a synthetic private-key marker in the redaction regression fixture,
with no private identity, internal host or real token match.

# 0.8 candidate acceptance

Status: `0.8.0rc1` is the candidate for public evaluation. This report separates
controlled engineering rehearsal from independent first use. No production
service, live credential, database or adapter was changed by these rehearsals.

## Evidence recorded on 2026-11-22

| Area | Evidence | Result |
| --- | --- | --- |
| Regression | 144 tests on Python 3.13.13/PostgreSQL 18.4; six-job CI in PR #10 covers Python 3.11–3.14, dependency floor and PostgreSQL 16/18 | Passed |
| Native installation | New venv, built wheel, execution outside the source checkout; imported module confirmed under the venv's site-packages | Passed |
| Native continuity | Two managed credentials/principals, all eight MCP tools, handoff, new processes retaining both bindings | Passed |
| Native recovery | Real custom-format dump restored into a second empty database; normalized fingerprints and both original bindings matched | Passed |
| Reader | Authenticated native export; namespace separation and live-revocation cleanup covered by integration tests | Passed |
| Historical upgrade | Actual v0.7.1 source, four principals, two projects, ten events; candidate and old-binary recovery copies verified | Passed in P3 |
| Docker runtime | Fresh database, host-owned private token overlay, two real MCP clients, PostgreSQL/app restart, healthy reader and restored-copy fingerprints/bindings | Passed locally using cached dependency image |
| Public Docker build | Unmodified Dockerfile from public source in the installation CI job | Passed in PR #11 and main CI; local index timeout described below |
| Distribution | Matching candidate versions, official Registry schema validation, matching wheel source, private-file archive exclusions, builds and twine checks | Passed; final CI is recorded in the P5 PR |
| Independent first use | 2–3 developers follow the public guide without source edits or live coaching | Not yet performed |

Native scripted onboarding reached its first two-identity handoff in **12.54
seconds**, with **16.42 seconds** for that rehearsal including dump/restore. These
figures start with the wheel already installed and PostgreSQL already running;
they are not a human installation time or a claim about the 15–20 minute target.
The dump was 25,329 bytes and contained synthetic data only.

Docker scripted onboarding reached its first two-identity handoff in **15.29
seconds**, with **37.72 seconds** including service restart and restoration after
the image and database were already ready. Its synthetic dump was 24,645 bytes.
The local source build could not read the PyPI index reliably (network read
timeout). To separate network availability from runtime correctness, the candidate
wheel was installed offline over the previously cached dependency image and
`pip check` passed. This is not claimed as a clean public-source image build.
The installation CI job passed the unmodified public Dockerfile in both
[PR #11](https://github.com/jessysw/contitext/actions/runs/45006180468) and
[main](https://github.com/jessysw/contitext/actions/runs/45006546938). No dependency requirement was weakened to bypass the failure.

## Repeatable checks

Use dedicated disposable databases. The regression suite resets its test schema;
never point it at a live or restored deployment database.

```sh
python -m pytest
python -m build
python -m twine check dist/*
python scripts/check_distribution.py dist
```

The CI installation job installs the built wheel into a fresh environment, runs
outside the checkout, then exercises a separate Compose stack and optional
reader. The six compatibility jobs retain the complete regression suite. Local
rehearsal additionally follows [two-agent setup](two-agents.md), restarts clients,
and restores an actual dump using [the recovery procedure](self-hosting.md#backup-and-recovery-rehearsal).

For a native candidate, install the built wheel in a new venv, run `init`,
`migrate`, `admin seed --if-empty`, `doctor` and `mcp-smoke` with its private config.
Import the initial credential, select database mode, provision a second principal,
grant membership and the project ACL, then issue its private token file. Generate
separate `client-config` JSON files and use actual stdio clients to bind, record a
checkpoint/handoff and read it from the second identity. Start fresh processes
and read the persisted bindings. Snapshot integrity, dump, restore to an empty
copy, compare fingerprints, and repeat the reads against that copy.

For Docker, follow the public guide in a separate checkout with a unique Compose
project name and unused localhost port. Use the documented host-owned token-file
bind mount and generated `--credential-file` connection. Verify `doctor`, both
clients, the optional reader, container recreation and restored-copy fingerprints.
Stop only that disposable stack after the rehearsal. Never use the test suite to
validate a restored production backup.

## Remaining release gate

Invite 2–3 independent developers to use the candidate guide and record:
installation path, OS/Python/PostgreSQL/Compose versions, actual time to first
handoff, where help was required, and redacted errors. Do not collect tokens or
private project content. Resolve blocking findings before stable publication and
broad promotion. An automated rehearsal or maintainer review does not satisfy
this independent-use gate.

Merging the five development deliveries does not publish a package, create a
release tag, update the MCP Registry or migrate a live deployment. The release
tracker remains open for independent acceptance and stable promotion. Candidate
publication enables these trials; it does not claim that they have occurred.

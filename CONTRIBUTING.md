# Contributing

Use English for commit messages, issues, pull requests, reviews, release notes,
documentation, code comments, and user-facing CLI messages. Use `contitext:` in
documented chat commands; a full-width colon is a compatibility input only.

Use synthetic projects and identities in tests and documentation. Keep private
configuration, credentials, hostnames, conversation history, and project state out
of commits. Add regression tests for behavior changes and document API changes.

## Development workflow

Use short-lived branches and pull requests against `main`. Keep each PR focused
on one independently reviewable change, including its tests and documentation.
Use descriptive names such as `feat/managed-credentials`, `fix/reader-refresh`,
or `docs/installation`; a version roadmap is not a long-lived integration branch.

1. Track a release-sized effort in one issue with a checklist and links to the
   relevant PRs. Create separate issues when a problem needs its own discussion.
2. Start a focused branch from current `main`. Open a draft PR if work is still
   incomplete; otherwise open it ready for review. Describe the user-visible
   behavior, compatibility impact, and validation in English.
3. Review the final diff and run the full CI matrix before merging. Address
   failures and review findings in the same PR. Honor any configured review and
   branch protection requirements; do not bypass them.
4. Squash merge completed PRs so `main` has one descriptive commit per change.
   Follow-up fixes remain visible in the PR without cluttering the main history.
   Do not rewrite published main history or released tags.
5. Delete merged remote branches and start the next change from updated `main`.
   Keep the tracking issue and unreleased changelog current.

`main` contains integrated development; tagged releases and PyPI packages are the
published versions. A completed feature may merge before its target release is
ready. Record such features under **Unreleased** and clearly label unreleased
documentation. Bump and align package/Registry versions in a release-preparation
PR, then follow [the release guide](docs/releasing.md) after the release gates pass.
Do not publish a package or change a running deployment merely because a feature
PR has merged. Use [GitHub flow](https://docs.github.com/en/get-started/using-github/github-flow)
as the underlying workflow.

## Local tests

Use standard CPython 3.11–3.14 and a **dedicated disposable** PostgreSQL 16+ database.
Tests drop and recreate its public schema. Never point tests at an application DB.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test,release]'
docker run -d --name contitext-tests -p 127.0.0.1:55439:5432 \
  -e POSTGRES_USER=contitext -e POSTGRES_PASSWORD=test-only \
  -e POSTGRES_DB=contitext_test postgres:16
export CONTITEXT_TEST_DATABASE_URL='postgresql+psycopg://contitext:test-only@127.0.0.1:55439/contitext_test'
# Wait until pg_isready succeeds before running pytest.
docker exec contitext-tests pg_isready -U contitext -d contitext_test
pytest
python -m build
python -m twine check dist/*
docker stop contitext-tests
```

CI uses a fresh PostgreSQL service for each Python version, with PostgreSQL 16
and a separate PostgreSQL 18 job. An additional Python
3.14 job tests the Psycopg, Pydantic, and SQLAlchemy compatibility floors:

```sh
python -m pip install -e '.[test,release]' -c tests/python314-compatibility.txt
python -m pip check
pytest
```

Run this in a separate Python 3.14 virtual environment with a disposable database.
The constraints exercise selected dependency floors, not every possible dependency
combination. Free-threaded builds are not part of the supported test matrix.

Existing service tests cover authorization, events, concurrency, bindings, restart recovery, real MCP
stdio, migrations, search, and filesystem projection. Public packaging and privacy
checks run without access to any private deployment.

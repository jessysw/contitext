# Contributing

Use English for commit messages, issues, pull requests, reviews, release notes,
documentation, code comments, and user-facing CLI messages. Use ASCII `!!` in
documented chat commands; full-width punctuation is a compatibility input only.

Use synthetic projects and identities in tests and documentation. Keep private
configuration, credentials, hostnames, conversation history, and project state out
of commits. Add regression tests for behavior changes and document API changes.

## Local tests

Use Python 3.11 or 3.12 and a **dedicated disposable** PostgreSQL 16 database.
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

CI uses a fresh PostgreSQL service for each Python version. Existing service tests
cover authorization, events, concurrency, bindings, restart recovery, real MCP
stdio, migrations, search, and filesystem projection. Public packaging and privacy
checks run without access to any private deployment.

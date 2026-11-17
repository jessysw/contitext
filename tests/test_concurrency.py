from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import create_engine, text

from contitext.db import create_session_factory
from contitext.repository import Repository
from contitext.service import ContextService
from test_events import make_event_request, seed_event_access


def test_concurrent_event_inserts_are_complete_and_exactly_once(
    migrated_database_url: str,
) -> None:
    writer, _ = seed_event_access(migrated_database_url)
    engine = create_engine(migrated_database_url, pool_size=12, max_overflow=20)
    service = ContextService(Repository(create_session_factory(engine)))
    count = 64
    requests = [
        make_event_request(
            source_kind=("hermes", "openclaw", "codex", "claude-code")[number % 4],
            source_id=f"source:{number}:CaseSensitive/ß",
            idempotency_key=f"parallel-event-{number}",
        )
        for number in range(count)
    ]
    try:
        with ThreadPoolExecutor(max_workers=20) as executor:
            events = list(executor.map(lambda item: service.record_context(writer, item), requests))
        assert len({event.event_id for event in events}) == count
        assert {event.source_id for event in events} == {item.source_id for item in requests}

        retries = requests[::7]
        with ThreadPoolExecutor(max_workers=12) as executor:
            retried = list(executor.map(lambda item: service.record_context(writer, item), retries))
        original_by_key = {event.idempotency_key: event.event_id for event in events}
        assert all(original_by_key[event.idempotency_key] == event.event_id for event in retried)

        with engine.connect() as connection:
            total = connection.execute(
                text("SELECT count(*) FROM context_events WHERE project_id = 'alpha'")
            ).scalar_one()
            duplicate_groups = connection.execute(text("""
                SELECT count(*) FROM (
                    SELECT idempotency_key FROM context_events
                    WHERE project_id = 'alpha'
                    GROUP BY idempotency_key HAVING count(*) <> 1
                ) AS duplicates
            """)).scalar_one()
        assert total == count
        assert duplicate_groups == 0
    finally:
        engine.dispose()


def test_concurrent_retries_of_one_key_return_one_event(
    migrated_database_url: str,
) -> None:
    writer, _ = seed_event_access(migrated_database_url)
    engine = create_engine(migrated_database_url, pool_size=12, max_overflow=12)
    service = ContextService(Repository(create_session_factory(engine)))
    request = make_event_request(idempotency_key="same-concurrent-key")
    try:
        with ThreadPoolExecutor(max_workers=16) as executor:
            events = list(executor.map(lambda _: service.record_context(writer, request), range(32)))
        assert len({event.event_id for event in events}) == 1
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM context_events WHERE project_id='alpha'")
            ).scalar_one() == 1
    finally:
        engine.dispose()

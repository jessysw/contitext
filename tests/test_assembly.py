"""Explicit lifecycle, isolation, task relevance and whole-response budget contracts."""
from concurrent.futures import ThreadPoolExecutor
import json
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from pydantic import ValidationError

from contitext.auth import ProjectNotFoundError
from contitext.db import create_session_factory
from contitext.repository import Repository, IdempotencyConflictError
from contitext.schemas import BindProjectRequest, EventMetadata, HandoffRequest, RecordContextRequest
from contitext.service import ContextService
from test_events import seed_event_access


@pytest.fixture
def setup(migrated_database_url):
    writer, reader = seed_event_access(migrated_database_url)
    engine = create_engine(migrated_database_url)
    service = ContextService(Repository(create_session_factory(engine)))
    yield service, writer, reader, engine
    engine.dispose()


def record(service, writer, kind, text='progress', *, metadata=None, key=None, project='alpha'):
    request = RecordContextRequest(project_id=project, scope_id='scope:exact', session_id='session:exact',
        agent_id=str(writer.principal_id), source_kind='test', source_id=key or str(uuid4()),
        event_kind=kind, payload={'summary':text}, idempotency_key=key or str(uuid4()), event_metadata=metadata)
    return service.record_context(writer, request), request


def handoff(service, writer, summary, task=None):
    return service.create_handoff(writer, HandoffRequest(project_id='alpha',scope_id='scope:exact',session_id='s',
        agent_id=str(writer.principal_id),source_kind='test',source_id=str(uuid4()),idempotency_key=str(uuid4()),
        summary=summary,next_action='Continue verified work', event_metadata=EventMetadata(task_id=task) if task else None))


def test_effective_lifecycle_retries_and_history(setup):
    service,writer,_,_=setup
    first,_=record(service,writer,'decision','Use first approach')
    second,request=record(service,writer,'decision','Use revised approach',metadata=EventMetadata(supersedes=first.event_id))
    assert service.record_context(writer,request).event_id==second.event_id
    with pytest.raises(ValueError,match='already'):
        record(service,writer,'decision',metadata=EventMetadata(supersedes=first.event_id))
    q,_=record(service,writer,'question','Which approach?')
    resolution,_=record(service,writer,'note','Resolved explicitly',metadata=EventMetadata(resolves=q.event_id))
    context=service.get_context(writer,'alpha')
    assert [x.event_id for x in context.recent_decisions]==[second.event_id]
    assert context.unresolved_questions==[]
    found=service.search_context(writer,'alpha','approach')
    assert {x.event.event_id for x in found.results}>={first.event_id,second.event_id,q.event_id}
    # Unknown historical payload keys never acquire lifecycle authority.
    request=request.model_copy(update={'idempotency_key':'legacy-keys','event_metadata':None,'event_kind':'note',
                                       'payload':{'supersedes':str(second.event_id),'task_id':'other'}})
    service.record_context(writer,RecordContextRequest.model_validate(request))
    assert service.get_context(writer,'alpha').recent_decisions[0].event_id==second.event_id


def test_relation_validation_and_no_cross_project_or_task_disclosure(setup):
    service,writer,reader,_=setup
    d,_=record(service,writer,'decision',metadata=EventMetadata(task_id='task-a'))
    for metadata,kind in [(EventMetadata(supersedes=d.event_id),'decision'),
                          (EventMetadata(task_id='task-a',resolves=d.event_id),'note'),
                          (EventMetadata(task_id='task-a',supersedes=d.event_id,candidate=True),'decision'),
                          (EventMetadata(supersedes=uuid4()),'decision')]:
        with pytest.raises(ValueError):record(service,writer,kind,metadata=metadata)
    service.bind_project(reader,BindProjectRequest(project_id='beta',scope_id='scope:exact',session_id='s'))
    hidden,_=record(service,reader,'decision',project='beta')
    with pytest.raises(ValueError,match='unavailable or incompatible'):
        record(service,writer,'decision',metadata=EventMetadata(supersedes=hidden.event_id))
    with pytest.raises(ProjectNotFoundError):service.get_context(writer,'beta',token_budget=4000)


def test_task_handoff_priority_global_fallback_and_candidates(setup):
    service,writer,_,_=setup
    global_h=handoff(service,writer,'Global handoff')
    scoped=handoff(service,writer,'Task A handoff','task-a')
    handoff(service,writer,'Unrelated task B latest','task-b')
    decision,_=record(service,writer,'decision','Global decision')
    manual,_=record(service,writer,'checkpoint','Verified checkpoint')
    candidate,_=record(service,writer,'checkpoint','Unverified automatic progress',metadata=EventMetadata(candidate=True,task_id='task-a'))
    a=service.get_context(writer,'alpha',task_id='task-a',token_budget=8000)
    assert a.context['handoff']['event_id']==str(scoped.event_id)
    assert a.context['checkpoint']['event_id']==str(manual.event_id)
    assert a.context['progress_candidates'][0]['event_id']==str(candidate.event_id)
    assert a.context['decisions'][0]['event_id']==str(decision.event_id)
    b=service.get_context(writer,'alpha',task_id='missing',token_budget=8000)
    assert b.context['handoff']['event_id']==str(global_h.event_id)
    assert b.context['progress_candidates']==[]
    assert 'Unrelated task B' not in b.model_dump_json()
    legacy=service.get_context(writer,'alpha')
    assert legacy.status.event_id==manual.event_id
    global_only=service.get_context(writer,'alpha',token_budget=8000)
    assert global_only.context['handoff']['event_id']==str(global_h.event_id)


def test_budget_is_deterministic_includes_serialized_envelope_and_skips_oversized(setup):
    service,writer,_,_=setup
    for i in range(15):record(service,writer,'decision','Decision '+str(i)+' 漢字'*80)
    record(service,writer,'question','x'*100000)
    for budget in (1024,2000,4000,8000):
        a=service.get_context(writer,'alpha',token_budget=budget)
        b=service.get_context(writer,'alpha',token_budget=budget)
        assert a==b
        assert len(a.model_dump_json().encode())==a.used_budget<=budget
        assert a.omitted_events>0
        assert not a.context['questions']
    for bad in (0,True,4000.5,32001):
        with pytest.raises(ValidationError):service.get_context(writer,'alpha',token_budget=bad)
    with pytest.raises(ValidationError):service.get_context(writer,'alpha',task_id='')


def test_concurrent_supersession_has_one_winner(setup):
    service,writer,_,_=setup
    first,_=record(service,writer,'decision','Before')
    def replace(_):
        try:return record(service,writer,'decision','After',metadata=EventMetadata(supersedes=first.event_id))[0].event_id
        except ValueError:return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(replace,range(2)))
    assert sum(x is not None for x in results)==1
    assert len(service.get_context(writer,'alpha').recent_decisions)==1

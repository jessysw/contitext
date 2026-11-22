"""Explicit lifecycle reduction and deterministic, conservatively bounded context."""
from sqlalchemy import String, cast, exists, or_, select
from sqlalchemy.orm import aliased

from contitext.models import ContextEvent
from contitext.schemas import AssembledContext

ALL_TASKS = object()


def validate_lifecycle(session, project_id, request):
    meta = request.event_metadata
    if meta is None:
        return
    if meta.supersedes and meta.resolves or meta.candidate and (meta.supersedes or meta.resolves):
        raise ValueError('candidate events cannot change lifecycle; use one explicit relation')
    relation = 'supersedes' if meta.supersedes else 'resolves' if meta.resolves else None
    if relation is None:
        return
    expected_kind, target_kind = ('decision', 'decision') if relation == 'supersedes' else ('note', 'question')
    target_id = getattr(meta, relation)
    target = session.scalar(select(ContextEvent).where(ContextEvent.project_id == project_id,
                                                       ContextEvent.event_id == target_id))
    other = (target.event_metadata or {}) if target is not None else {}
    if (request.event_kind.value != expected_kind or target is None or target.event_kind != target_kind
            or other.get('candidate') is True or other.get('task_id') != meta.task_id):
        raise ValueError('lifecycle target unavailable or incompatible')
    previous = session.scalar(select(ContextEvent.event_id).where(
        ContextEvent.project_id == project_id,
        ContextEvent.event_metadata[relation].astext == str(target_id),
    ).limit(1))
    if previous is not None:
        raise ValueError('lifecycle target is already superseded or resolved')


def event_selection(project_id, kind, *, task_id=ALL_TASKS, candidate=False, limit=20):
    statement = select(ContextEvent).where(ContextEvent.project_id == project_id,
                                            ContextEvent.event_kind == kind)
    flag = ContextEvent.event_metadata['candidate'].as_boolean()
    statement = statement.where(flag.is_(True) if candidate else flag.is_not(True))
    if kind in {'question','decision'} and not candidate:
        relation = 'resolves' if kind == 'question' else 'supersedes'
        newer = aliased(ContextEvent)
        statement = statement.where(~exists(select(newer.event_id).where(
            newer.project_id == ContextEvent.project_id,
            newer.event_metadata[relation].astext == cast(ContextEvent.event_id, String),
            newer.event_metadata['candidate'].as_boolean().is_not(True),
        )))
        if kind == 'question':
            # Historical payload flags retain their original meaning; arbitrary
            # old payload relation/task keys are never interpreted as metadata.
            statement = statement.where(ContextEvent.payload['resolved'].astext.is_distinct_from('true'))
    if task_id is not ALL_TASKS:
        task = ContextEvent.event_metadata['task_id'].astext
        statement = statement.where(task.is_(None) if task_id is None else or_(task == task_id, task.is_(None)))
        if task_id is not None:
            statement = statement.order_by((task == task_id).desc().nulls_last())
    return statement.order_by(ContextEvent.created_at.desc(), ContextEvent.event_id.desc()).limit(limit)


def compact_event(event):
    metadata = event.event_metadata or {}
    return {'event_id': str(event.event_id), 'event_kind': event.event_kind,
            'created_at': event.created_at.isoformat(), 'principal_id': str(event.principal_id),
            'task_id': metadata.get('task_id'), 'candidate': metadata.get('candidate',False),
            'payload': event.payload}


def measure(bundle):
    # Include the budget fields themselves. A fixed point avoids off-by-one errors
    # when the number of digits in the reported size changes.
    for _ in range(8):
        size = len(bundle.model_dump_json().encode('utf-8'))
        if size == bundle.used_budget:
            return size
        bundle.used_budget = size
    raise ValueError('cannot measure context budget')


def assemble(session, project, options):
    context = {'overview': {'display_name':project.project.display_name, 'status':project.project.status},
               'handoff':None, 'decisions':[], 'questions':[], 'checkpoint':None, 'progress_candidates':[]}
    bundle = AssembledContext(project_id=project.reference, task_id=options.task_id,
                              token_budget=options.token_budget, context=context)
    context = bundle.context
    pool = []
    for section, kind, candidate, limit in [('handoff','handoff',False,1), ('decisions','decision',False,20),
                                           ('questions','question',False,20), ('checkpoint','checkpoint',False,1),
                                           ('progress_candidates','checkpoint',True,3)]:
        for event in session.scalars(event_selection(project.id, kind, task_id=options.task_id, candidate=candidate, limit=limit)):
            pool.append((section, compact_event(event)))
    bundle.omitted_events = len(pool)
    if measure(bundle) > options.token_budget:
        del context['overview']['display_name']
    if measure(bundle) > options.token_budget:
        raise ValueError('budget too small for project identity')
    for section, event in pool:
        old = context[section]
        context[section] = [*old, event] if isinstance(old, list) else event
        bundle.omitted_events -= 1
        if measure(bundle) > options.token_budget:
            context[section] = old
            bundle.omitted_events += 1
            measure(bundle)
    return bundle

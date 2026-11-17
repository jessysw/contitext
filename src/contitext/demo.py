"""A small real HTTP handoff between two example agents. Writes to project demo."""

import json
import os
from urllib.request import Request, urlopen
from uuid import uuid4


def main() -> None:
    base = os.environ.get("CONTITEXT_HTTP_URL", "http://127.0.0.1:8000").rstrip("/")
    token = os.environ["CONTITEXT_MCP_TOKEN"]
    run = uuid4().hex

    def call(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = Request(base + path, data=data, method=method,
                          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urlopen(request, timeout=10) as response:
            return json.load(response)

    scope_a, scope_b = f"demo:agent-a:{run}", f"demo:agent-b:{run}"
    call("PUT", f"/v1/scopes/{scope_a}/binding", {"project_id": "demo", "session_id": run})
    provenance = {"scope_id": scope_a, "session_id": run, "agent_id": "agent-a",
                  "source_kind": "demo", "source_id": run}
    event = {**provenance, "event_kind": "decision", "payload": {"text": "Use PostgreSQL for durable project state."},
             "idempotency_key": f"demo-decision:{run}"}
    first = call("POST", "/v1/projects/demo/events", event)
    retry = call("POST", "/v1/projects/demo/events", event)
    assert first["event_id"] == retry["event_id"], "retry created a duplicate"
    call("POST", "/v1/projects/demo/events", {
        **provenance, "event_kind": "checkpoint", "payload": {"summary": "Storage design is agreed."},
        "idempotency_key": f"demo-checkpoint:{run}",
    })
    handoff = call("POST", "/v1/projects/demo/handoffs", {
        **provenance, "summary": "Design ready for implementation.",
        "next_action": "Implement and test the first endpoint.",
        "completed": ["Storage decision"], "current": ["Endpoint implementation"], "blockers": [],
        "idempotency_key": f"demo-handoff:{run}",
    })
    call("PUT", f"/v1/scopes/{scope_b}/binding", {"project_id": "demo", "session_id": run})
    resumed = call("GET", "/v1/projects/demo/context")
    assert resumed["latest_handoff"]["event_id"] == handoff["event_id"]
    print(json.dumps({"agent_b_resumed": resumed["overview"]["project_id"],
                      "next_action": resumed["latest_handoff"]["payload"]["next_action"],
                      "idempotent_retry": "passed"}, indent=2))


if __name__ == "__main__":
    main()

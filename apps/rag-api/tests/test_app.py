import json

from fastapi.testclient import TestClient

from conftest import signed_in
from fake_model import FakeModelServer


def records(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_health_and_readiness(make_app, model):
    app = make_app(model)
    # Without the lifespan, startup has not run and the app is not ready.
    assert TestClient(app).get("/readyz").status_code == 503
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "alive"}
        assert client.get("/readyz").status_code == 200


def test_readiness_does_not_depend_on_the_model(make_app):
    with signed_in(make_app(FakeModelServer(healthy=False))) as client:
        assert client.get("/readyz").status_code == 200
        status = client.get("/api/status").json()
    assert status["model"] == {"runtime": "llamacpp", "alias": "assistant-chat", "status": "unavailable"}
    assert status["retrieval"] == {"status": "ok"}
    assert status["promptVersion"] == "grounded-v1"
    assert status["admission"] == {"active": 0, "limit": 3}


def test_chat_is_logged_without_question_or_answer_text(make_app, model, log_stream):
    with signed_in(make_app(model)) as client:
        response = client.post("/api/chat", json={"question": "private-question-text"})
    entry, = [r for r in records(log_stream) if r["event"] == "chat_completed"]
    assert entry.items() >= {
        "request_id": response.headers["x-request-id"], "outcome": "complete", "passages": 2,
        "generated_tokens": 3, "invalid_citations": 0, "prompt_version": "grounded-v1",
    }.items()
    assert "private-question-text" not in log_stream.getvalue()
    assert "Pods restart" not in log_stream.getvalue()

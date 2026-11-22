from prometheus_client import REGISTRY
import pytest

from conftest import parse_events, signed_in, terminal_events
from fake_model import FakeModelServer


def sample(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0


def ask(app, question="Why do Pods restart?"):
    with signed_in(app) as client:
        response = client.post("/api/chat", json={"question": question})
        return response, app.state.admission.active


def test_normal_stream_ends_with_one_done_event(make_app, model):
    response, active = ask(make_app(model))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_events(response.text)
    assert [name for name, _ in events] == ["meta", "token", "token", "token", "done"]
    meta, done = events[0][1], events[-1][1]
    assert meta["requestId"] == response.headers["x-request-id"]
    assert [source["label"] for source in meta["sources"]] == ["S1", "S2"]
    assert "".join(data["text"] for name, data in events if name == "token") == "Pods restart [S1]."
    assert done["status"] == "complete"
    assert done["usage"] == {"promptTokens": 42, "completionTokens": 3}
    assert done["citations"] == {"valid": ["S1"], "invalid": []}
    assert active == 0


def test_the_model_is_always_sent_the_output_limit(make_app, model):
    ask(make_app(model))
    body, = model.chat_bodies
    assert body["max_tokens"] == 384 and body["temperature"] == 0
    assert body["stream"] is True
    assert body["messages"][0]["role"] == "system"


def test_output_limit_reached_is_a_length_finish(make_app):
    response, _ = ask(make_app(FakeModelServer(finish_reason="length")))
    terminal, = terminal_events(parse_events(response.text))
    assert terminal[0] == "done"
    assert terminal[1]["status"] == "length"


def test_invalid_citations_are_reported_and_counted(make_app):
    before = sample("rag_invalid_citations_total")
    response, _ = ask(make_app(FakeModelServer(tokens=["See ", "[S1] ", "and ", "[S9]."])))
    done = parse_events(response.text)[-1][1]
    assert done["citations"] == {"valid": ["S1"], "invalid": ["S9"]}
    assert sample("rag_invalid_citations_total") == before + 1


@pytest.mark.parametrize("model, overrides, reason, partial", [
    (FakeModelServer(mode="fail_mid", fail_after=1), {}, "upstream_failed", True),
    (FakeModelServer(mode="no_finish"), {}, "upstream_failed", True),
    (FakeModelServer(mode="http_error"), {}, "upstream_failed", False),
    (FakeModelServer(mode="stall", fail_after=1), {"stall_timeout_seconds": 1, "request_deadline_seconds": 5}, "stalled", True),
    (FakeModelServer(tokens=["word "] * 20, delay=0.3), {"stall_timeout_seconds": 1, "request_deadline_seconds": 2}, "deadline", True),
], ids=["mid-stream failure", "no finish reason", "upstream HTTP error", "stall", "deadline"])
def test_failures_end_with_exactly_one_error_event(make_app, model, overrides, reason, partial):
    before = sample("rag_requests_total", status=reason)
    response, active = ask(make_app(model, **overrides))
    events = parse_events(response.text)
    assert events[0][0] == "meta"
    assert terminal_events(events) == [("error", {"reason": reason, "partial": partial})]
    assert events[-1][0] == "error"
    assert sample("rag_requests_total", status=reason) == before + 1
    assert active == 0
    if model.streams:
        assert model.closed


def test_unreachable_model_is_refused_before_streaming(make_app):
    response, active = ask(make_app(FakeModelServer(mode="unreachable")))
    assert response.status_code == 503
    assert response.json() == {"detail": "model_unavailable"}
    assert active == 0

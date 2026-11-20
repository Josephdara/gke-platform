
from rag_api.limits import AdmissionLimiter, RateLimiter

from conftest import signed_in


def test_admission_refuses_beyond_the_limit_and_frees_on_release():
    limiter = AdmissionLimiter(3)
    assert [limiter.try_acquire() for _ in range(4)] == [True, True, True, False]
    limiter.release()
    assert limiter.try_acquire()


def test_a_full_replica_answers_429_with_retry_after(make_app, model):
    app = make_app(model)
    for _ in range(3):
        assert app.state.admission.try_acquire()
    with signed_in(app) as client:
        response = client.post("/api/chat", json={"question": "Why?"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "10"
    assert model.chat_bodies == []


def test_rate_limit_window_slides():
    now = [0.0]
    limiter = RateLimiter(2, clock=lambda: now[0])
    assert limiter.check("a") == 0 and limiter.check("a") == 0
    assert limiter.check("a") == 60
    assert limiter.check("b") == 0
    now[0] = 59.5
    assert limiter.check("a") == 1
    now[0] = 60.0
    assert limiter.check("a") == 0


def test_rate_limited_caller_gets_429(make_app, model):
    app = make_app(model, rate_limit_per_minute=1)
    with signed_in(app) as client:
        assert client.post("/api/chat", json={"question": "Why?"}).status_code == 200
        response = client.post("/api/chat", json={"question": "Why?"})
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


def test_input_bounds(make_app, model):
    app = make_app(model)
    with signed_in(app) as client:
        assert client.post("/api/chat", json={"question": "x" * 2001}).status_code == 422
        assert client.post("/api/chat", json={"question": "   "}).status_code == 422
        # A client cannot choose its own output length.
        assert client.post("/api/chat", json={"question": "Why?", "max_tokens": 4000}).status_code == 422
        assert client.post("/api/chat", json={"question": "x" * 2000}).status_code == 200
    assert len(model.chat_bodies) == 1

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY


def sample(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0


def test_requests_are_counted_and_timed(app):
    counted = sample("http_requests_total", method="GET", route="/", status="200")
    timed = sample("http_request_duration_seconds_count", method="GET", route="/")
    with TestClient(app) as client:
        client.get("/")
    assert sample("http_requests_total", method="GET", route="/", status="200") == counted + 1
    assert sample("http_request_duration_seconds_count", method="GET", route="/") == timed + 1


def test_labels_are_bounded_and_errors_counted(app):
    @app.get("/failure")
    async def failure():
        raise RuntimeError("failure")

    expected = [
        {"method": "GET", "route": "unmatched", "status": "404"},
        {"method": "other", "route": "/", "status": "405"},
        {"method": "GET", "route": "/failure", "status": "500"},
    ]
    before = [sample("http_requests_total", **labels) for labels in expected]
    with TestClient(app) as client:
        client.get("/random-path-12345")
        client.request("BREW", "/")
        client.get("/failure")
    assert [sample("http_requests_total", **labels) for labels in expected] == [count + 1 for count in before]


def test_health_probes_are_not_counted(app):
    with TestClient(app) as client:
        client.get("/livez")
        client.get("/readyz")
    for route in ("/livez", "/readyz"):
        assert REGISTRY.get_sample_value("http_requests_total", {"method": "GET", "route": route, "status": "200"}) is None

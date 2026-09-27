import json
import re
from datetime import datetime
from uuid import UUID

from fastapi.testclient import TestClient
import pytest


def records(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_generated_request_id_and_log_fields(app, log_stream):
    with TestClient(app) as client:
        response = client.get("/")
    request_id = response.headers["x-request-id"]
    assert str(UUID(request_id)) == request_id
    entry, = [item for item in records(log_stream) if item["event"] == "http_request"]
    assert entry.items() >= {
        "severity": "INFO", "service": "platform-verification-api", "environment": "test",
        "release": "test-release", "request_id": request_id, "method": "GET", "path": "/", "status": 200,
    }.items()
    assert datetime.fromisoformat(entry["timestamp"]).utcoffset().total_seconds() == 0
    assert entry["duration_ms"] >= 0


def test_supplied_request_id(app, log_stream):
    with TestClient(app) as client:
        response = client.get("/", headers={"x-request-id": "build-123.test_1"})
    assert response.headers["x-request-id"] == "build-123.test_1"
    assert any(item.get("request_id") == "build-123.test_1" for item in records(log_stream))


@pytest.mark.parametrize("request_id", ["", "a" * 65, "bad id", "bad/id"])
def test_invalid_request_ids_are_replaced(app, request_id):
    with TestClient(app) as client:
        response = client.get("/", headers={"x-request-id": request_id})
    assert str(UUID(response.headers["x-request-id"])) == response.headers["x-request-id"]


def test_duplicate_request_id_headers_are_replaced(app):
    with TestClient(app) as client:
        response = client.get("/", headers=[("x-request-id", "first"), ("x-request-id", "second")])
    assert str(UUID(response.headers["x-request-id"])) == response.headers["x-request-id"]


def test_failed_requests_do_not_log_payloads(app, log_stream):
    with TestClient(app) as client:
        response = client.post("/?token=query-secret", content="body-secret", headers={"authorization": "Bearer header-secret"})
    assert response.status_code == 405
    entry, = [item for item in records(log_stream) if item["event"] == "http_request"]
    assert entry["status"] == 405
    assert entry["severity"] == "WARNING"
    assert entry["path"] == "/"
    assert not re.search("query-secret|body-secret|header-secret", log_stream.getvalue())


def test_unhandled_error_is_sanitized_and_correlated(app, log_stream):
    @app.get("/failure")
    async def failure():
        raise RuntimeError("private-exception-details")

    with TestClient(app) as client:
        response = client.get("/failure")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    entry, = [item for item in records(log_stream) if item["event"] == "http_request"]
    assert entry["request_id"] == response.headers["x-request-id"]
    assert entry["status"] == 500
    assert entry["error_type"] == "RuntimeError"
    assert entry["severity"] == "ERROR"
    assert "private-exception-details" not in log_stream.getvalue()

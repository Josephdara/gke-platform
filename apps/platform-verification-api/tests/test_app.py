import json

from fastapi.testclient import TestClient
import pytest

from platform_verification_api.app import create_app
from platform_verification_api.config import ConfigurationError


def test_service_identity(app):
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"service": "platform-verification-api", "version": "test-release"}


def test_liveness_is_independent_of_readiness(app):
    with TestClient(app) as client:
        assert client.get("/readyz").json() == {"status": "ready"}
        app.state.ready = False
        assert client.get("/readyz").status_code == 503
        assert client.get("/readyz").json() == {"status": "not_ready"}
        assert client.get("/livez").status_code == 200
        assert client.get("/livez").json() == {"status": "alive"}


def test_lifecycle(app, log_stream):
    assert app.state.ready is False
    with TestClient(app):
        assert app.state.ready is True
    assert app.state.ready is False
    events = [json.loads(line)["event"] for line in log_stream.getvalue().splitlines()]
    assert events == ["application_started", "application_stopped"]


def test_configuration_fails_before_application_start(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    with pytest.raises(ConfigurationError, match="ENVIRONMENT"):
        create_app()


def test_only_phase_two_routes(app):
    with TestClient(app) as client:
        for route in ("/backend", "/docs", "/openapi.json"):
            assert client.get(route).status_code == 404

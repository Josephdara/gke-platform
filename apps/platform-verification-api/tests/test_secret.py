import json

from fastapi.testclient import TestClient
import pytest

from platform_verification_api.app import create_app
from platform_verification_api.config import Settings
from platform_verification_api.logging import create_logger

VALUE = "private-secret-value"


def secret(label, value=VALUE):
    return json.dumps({"label": label, "value": value})


def events(stream, name):
    return [entry for entry in map(json.loads, stream.getvalue().splitlines()) if entry["event"] == name]


@pytest.fixture
def secret_path(tmp_path):
    return tmp_path / "secret.json"


@pytest.fixture
def secret_app(secret_path, log_stream):
    settings = Settings.from_env({"ENVIRONMENT": "test", "RELEASE_VERSION": "test-release", "SECRET_FILE": str(secret_path)})
    return create_app(settings, create_logger(settings, log_stream))


def test_label_is_served_and_value_is_never_exposed(secret_app, secret_path, log_stream):
    secret_path.write_text(secret("v1"))
    with TestClient(secret_app) as client:
        response = client.get("/")
        assert client.get("/readyz").status_code == 200
    assert response.json()["secretLabel"] == "v1"
    assert events(log_stream, "secret_loaded")[0]["secret_label"] == "v1"
    assert VALUE not in response.text + log_stream.getvalue()


def test_rotation_is_picked_up(secret_app, secret_path):
    secret_path.write_text(secret("v1"))
    with TestClient(secret_app) as client:
        assert client.get("/").json()["secretLabel"] == "v1"
        secret_path.write_text(secret("v2"))
        assert client.get("/").json()["secretLabel"] == "v2"


@pytest.mark.parametrize("content", [None, "not json", "[]", secret("bad label"), secret("v1", value="")])
def test_invalid_secret_at_startup_is_not_ready_until_fixed(secret_app, secret_path, log_stream, content):
    if content is not None:
        secret_path.write_text(content)
    with TestClient(secret_app) as client:
        assert client.get("/readyz").status_code == 503
        secret_path.write_text(secret("v2"))
        assert client.get("/readyz").status_code == 200
    assert len(events(log_stream, "secret_load_failed")) == 1


def test_invalid_rotation_keeps_last_valid_label(secret_app, secret_path, log_stream):
    secret_path.write_text(secret("v1"))
    with TestClient(secret_app) as client:
        secret_path.write_text("not json " + VALUE)
        assert client.get("/").json()["secretLabel"] == "v1"
        assert client.get("/readyz").status_code == 200
    failed, = events(log_stream, "secret_reload_failed")
    assert failed["error_type"] == "JSONDecodeError"
    assert VALUE not in log_stream.getvalue()

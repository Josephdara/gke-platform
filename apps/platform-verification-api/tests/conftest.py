import io

import pytest

from platform_verification_api.app import create_app
from platform_verification_api.config import Settings
from platform_verification_api.logging import create_logger


@pytest.fixture
def settings():
    return Settings.from_env({"ENVIRONMENT": "test", "RELEASE_VERSION": "test-release"})


@pytest.fixture
def log_stream():
    return io.StringIO()


@pytest.fixture
def app(settings, log_stream):
    return create_app(settings, create_logger(settings, log_stream))

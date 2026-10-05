import pytest

from platform_verification_api.config import ConfigurationError, Settings

BASE = {"ENVIRONMENT": "test", "RELEASE_VERSION": "release-123"}


def test_defaults():
    settings = Settings.from_env(BASE)
    assert settings.service_name == "platform-verification-api"
    assert settings.port == 8080
    assert settings.log_level == "INFO"
    assert settings.secret_file is None


def test_overrides():
    settings = Settings.from_env({**BASE, "SERVICE_NAME": "other-service", "APP_PORT": "9000", "LOG_LEVEL": "debug"})
    assert settings.service_name == "other-service"
    assert settings.environment == "test"
    assert settings.release_version == "release-123"
    assert settings.port == 9000
    assert settings.log_level == "DEBUG"


@pytest.mark.parametrize("field", ["ENVIRONMENT", "RELEASE_VERSION"])
def test_missing_required_fields(field):
    env = dict(BASE)
    del env[field]
    with pytest.raises(ConfigurationError, match=field):
        Settings.from_env(env)


@pytest.mark.parametrize("field", ["ENVIRONMENT", "RELEASE_VERSION", "SERVICE_NAME", "SECRET_FILE"])
@pytest.mark.parametrize("value", ["", "   ", "text\nvalue"])
def test_invalid_text(field, value):
    with pytest.raises(ConfigurationError, match=field):
        Settings.from_env({**BASE, field: value})


@pytest.mark.parametrize("value", ["", "0", "65536", "-1", "1.5", "abc", "１２３", "9" * 5000])
def test_invalid_port(value):
    with pytest.raises(ConfigurationError, match="APP_PORT"):
        Settings.from_env({**BASE, "APP_PORT": value})


@pytest.mark.parametrize("value", ["1", "65535"])
def test_port_boundaries(value):
    assert Settings.from_env({**BASE, "APP_PORT": value}).port == int(value)


def test_invalid_log_level_does_not_echo_value():
    with pytest.raises(ConfigurationError) as error:
        Settings.from_env({**BASE, "LOG_LEVEL": "sensitive-invalid-value"})
    assert "LOG_LEVEL" in str(error.value)
    assert "sensitive-invalid-value" not in str(error.value)

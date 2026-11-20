import pytest

from rag_api.config import ConfigurationError, Settings

BASE = {"ENVIRONMENT": "test", "RELEASE_VERSION": "release-123", "MODEL_URL": "http://staging-llm-cpu:8080/"}


def test_defaults():
    settings = Settings.from_env(BASE)
    assert settings.service_name == "rag-api"
    assert settings.model_url == "http://staging-llm-cpu:8080"
    assert settings.model_alias == "assistant-chat"
    assert (settings.admission_limit, settings.request_deadline_seconds, settings.stall_timeout_seconds) == (3, 120, 30)
    assert (settings.context_tokens, settings.output_tokens, settings.passage_tokens) == (4096, 384, 1200)
    assert (settings.history_turns, settings.max_input_chars, settings.rate_limit_per_minute) == (2, 2000, 10)


@pytest.mark.parametrize("field", ["ENVIRONMENT", "RELEASE_VERSION", "MODEL_URL"])
def test_missing_required_fields(field):
    env = dict(BASE)
    del env[field]
    with pytest.raises(ConfigurationError, match=field):
        Settings.from_env(env)


@pytest.mark.parametrize("value", ["staging-llm-cpu:8080", "ftp://model", "http://a b"])
def test_invalid_model_url(value):
    with pytest.raises(ConfigurationError, match="MODEL_URL"):
        Settings.from_env({**BASE, "MODEL_URL": value})


@pytest.mark.parametrize("field, value", [
    ("ADMISSION_LIMIT", "0"), ("ADMISSION_LIMIT", "65"), ("OUTPUT_TOKENS", "abc"),
    ("CONTEXT_TOKENS", "-1"), ("REQUEST_DEADLINE_SECONDS", "9"), ("APP_PORT", "65536"),
])
def test_invalid_integers(field, value):
    with pytest.raises(ConfigurationError, match=field):
        Settings.from_env({**BASE, field: value})


def test_output_and_passages_must_leave_room_in_the_slot():
    with pytest.raises(ConfigurationError, match="OUTPUT_TOKENS plus PASSAGE_TOKENS"):
        Settings.from_env({**BASE, "CONTEXT_TOKENS": "1584", "PASSAGE_TOKENS": "1200"})


def test_stall_timeout_must_be_shorter_than_the_deadline():
    with pytest.raises(ConfigurationError, match="STALL_TIMEOUT_SECONDS"):
        Settings.from_env({**BASE, "STALL_TIMEOUT_SECONDS": "120"})


def test_errors_do_not_echo_values():
    with pytest.raises(ConfigurationError) as error:
        Settings.from_env({**BASE, "LOG_LEVEL": "sensitive-invalid-value"})
    assert "sensitive-invalid-value" not in str(error.value)


def test_retrieval_is_off_without_a_database():
    settings = Settings.from_env(BASE)
    assert (settings.database_host, settings.embeddings_url, settings.similarity_floor) == (None, None, 0.0)
    assert (settings.database_user, settings.retrieval_top_k) == ("rag_api", 5)


@pytest.mark.parametrize("missing", ["DATABASE_PASSWORD_FILE", "EMBEDDINGS_URL"])
def test_a_database_needs_its_password_and_the_embeddings_server(missing):
    env = {**BASE, "DATABASE_HOST": "pgvector", "DATABASE_PASSWORD_FILE": "/run/p", "EMBEDDINGS_URL": "http://e:8080"}
    del env[missing]
    with pytest.raises(ConfigurationError, match=missing):
        Settings.from_env(env)


@pytest.mark.parametrize("field, value", [("SIMILARITY_FLOOR", "1.5"), ("SIMILARITY_FLOOR", "high"), ("RETRIEVAL_TOP_K", "6")])
def test_invalid_retrieval_settings(field, value):
    with pytest.raises(ConfigurationError, match=field):
        Settings.from_env({**BASE, field: value})

import pytest

from ingest.config import ConfigurationError, Settings

BASE = {"ENVIRONMENT": "test", "RELEASE_VERSION": "r", "CORPUS_SOURCE": "gs://bucket/corpus/rev",
        "EMBEDDINGS_URL": "http://embeddings:8080/", "DATABASE_HOST": "pgvector", "DATABASE_PASSWORD_FILE": "/run/p"}


def test_defaults():
    settings = Settings.from_env(BASE)
    assert settings.corpus_source == "gs://bucket/corpus/rev/"
    assert settings.embeddings_url == "http://embeddings:8080"
    assert (settings.database_user, settings.database_name, settings.report_bucket) == ("ingest", "rag", None)
    assert (settings.chunk_tokens, settings.overlap_tokens, settings.embedding_dimensions) == (300, 40, 384)


@pytest.mark.parametrize("field", ["CORPUS_SOURCE", "EMBEDDINGS_URL", "DATABASE_HOST", "DATABASE_PASSWORD_FILE"])
def test_required(field):
    env = dict(BASE)
    del env[field]
    with pytest.raises(ConfigurationError, match=field):
        Settings.from_env(env)


@pytest.mark.parametrize("change, field", [
    ({"CHUNK_TOKENS": "600"}, "CHUNK_TOKENS"), ({"OVERLAP_TOKENS": "150"}, "OVERLAP_TOKENS"),
    ({"EMBED_BATCH": "64"}, "EMBED_BATCH"), ({"EMBEDDINGS_URL": "embeddings:8080"}, "EMBEDDINGS_URL"),
])
def test_invalid(change, field):
    with pytest.raises(ConfigurationError, match=field):
        Settings.from_env({**BASE, **change})

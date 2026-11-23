import pytest

from ingest.embed import RETRIES, EmbeddingError

from fake_tei import FakeTei


def test_a_busy_server_is_retried_after_its_retry_after_and_then_given_up_on():
    waits = []
    tei = FakeTei(busy=2)
    assert len(tei.client(sleep=waits.append).embed(["a b", "c"])) == 2
    assert waits == [2.0, 2.0]
    with pytest.raises(EmbeddingError, match="HTTP 429"):
        FakeTei(busy=RETRIES + 1).client().embed(["a"])

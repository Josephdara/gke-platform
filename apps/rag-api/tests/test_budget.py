import asyncio

import pytest

from rag_api.budget import Budget, BudgetExceeded, fit_prompt
from rag_api.prompt import Passage, build_messages

from fake_model import FakeModelServer

PASSAGES = [Passage(f"doc#{n}", f"Title {n}", " ".join(["word"] * 20)) for n in range(1, 6)]
HISTORY = [
    {"role": "user", "content": "first question"}, {"role": "assistant", "content": "first answer"},
    {"role": "user", "content": "second question"}, {"role": "assistant", "content": "second answer"},
    {"role": "user", "content": "third question"}, {"role": "assistant", "content": "third answer"},
]


def fit(question="Why do Pods restart?", history=(), passages=PASSAGES, context=4096, output=384, passage=1200, turns=2):
    backend = FakeModelServer().backend()
    return asyncio.run(fit_prompt(question, list(history), list(passages), backend, Budget(context, output, passage, turns)))


def count(messages):
    return asyncio.run(FakeModelServer().backend().count_tokens(messages))


def test_everything_fits():
    fitted = fit()
    assert fitted.passages == PASSAGES
    assert fitted.dropped_passages == 0
    assert fitted.prompt_tokens == count(fitted.messages)
    assert fitted.messages[0]["role"] == "system"


def test_passage_budget_drops_lowest_ranked_first():
    # Each passage costs 23 counted words ("[Sn]", "Title", "n", 20 words), so 50 keeps two.
    fitted = fit(passage=50)
    assert fitted.passages == PASSAGES[:2]
    assert fitted.dropped_passages == 3


def test_prompt_exactly_at_the_limit_fits_and_one_token_over_drops_a_passage():
    full = count(build_messages("Why do Pods restart?", [], PASSAGES))
    assert fit(context=full + 384).passages == PASSAGES
    over = fit(context=full + 383)
    assert over.passages == PASSAGES[:4]
    assert over.prompt_tokens <= full + 383 - 384


def test_history_keeps_only_the_most_recent_turns():
    fitted = fit(history=HISTORY, turns=2)
    contents = [m["content"] for m in fitted.messages]
    assert "first question" not in contents
    assert contents[1:5] == ["second question", "second answer", "third question", "third answer"]
    assert fitted.dropped_turns == 1


def test_history_is_dropped_before_the_question_when_over_the_limit():
    alone = count(build_messages("Why do Pods restart?", [], []))
    fitted = fit(history=HISTORY, passages=[], context=alone + 384 + 3)
    assert [m["role"] for m in fitted.messages] == ["system", "user"]
    assert fitted.dropped_turns == 3


def test_a_question_that_cannot_fit_is_refused():
    with pytest.raises(BudgetExceeded):
        fit(question=" ".join(["long"] * 500), passages=[], context=512, output=384, passage=0)

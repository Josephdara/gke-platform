import pytest

from rag_api.prompt import GENERAL_PROMPT, SYSTEM_PROMPT, Passage, build_messages, check_citations


@pytest.mark.parametrize("answer, valid, invalid", [
    ("Probes restart containers [S1].", ["S1"], []),
    ("See [S1] and [S2], and again [S1].", ["S1", "S2"], []),
    ("Unknown source [S7] and [S0].", [], ["S7", "S0"]),
    ("Mixed [S2] [S9].", ["S2"], ["S9"]),
    ("Malformed [S] [s1] [S1a] (S1) S1.", [], []),
    ("No citations at all.", [], []),
])
def test_citations_are_checked_against_the_retrieved_set(answer, valid, invalid):
    result = check_citations(answer, passage_count=2)
    assert result.valid == valid
    assert result.invalid == invalid


def test_every_citation_is_invalid_without_passages():
    assert check_citations("Answer [S1].", passage_count=0).invalid == ["S1"]


def test_each_system_prompt_comes_first_and_never_varies():
    first = build_messages("one?", [], [Passage("a", "A", "text a")])
    second = build_messages("two?", [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}],
                            [Passage("b", "B", "text b")])
    assert first[0] == second[0] == {"role": "system", "content": SYSTEM_PROMPT}


def test_passages_are_numbered_and_marked_untrusted():
    messages = build_messages("Why?", [], [Passage("a", "Probes", "text a"), Passage("b", "Pods", "text b")])
    user = messages[-1]["content"]
    assert "untrusted" in user
    assert user.index("[S1] Probes") < user.index("[S2] Pods") < user.index("Question: Why?")


def test_without_passages_the_general_prompt_gets_the_bare_question():
    messages = build_messages("ping", [], [])
    assert messages == [{"role": "system", "content": GENERAL_PROMPT}, {"role": "user", "content": "ping"}]

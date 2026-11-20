"""Prompt budget: fit the system prompt, history, passages, question and reserved output into one slot."""

from dataclasses import dataclass

from .inference import InferenceBackend, Message
from .prompt import Passage, build_messages, passage_heading


class BudgetExceeded(Exception):
    """Even the question alone does not fit in the slot with the reserved output."""


@dataclass(frozen=True)
class Budget:
    context_tokens: int
    output_tokens: int
    passage_tokens: int
    history_turns: int


@dataclass(frozen=True)
class FittedPrompt:
    messages: list[Message]
    passages: list[Passage]
    prompt_tokens: int
    dropped_passages: int
    dropped_turns: int


async def fit_prompt(
    question: str,
    history: list[Message],
    passages: list[Passage],
    backend: InferenceBackend,
    budget: Budget,
) -> FittedPrompt:
    limit = budget.context_tokens - budget.output_tokens
    # A turn is a user message and the answer to it; only the most recent turns are kept.
    turns = [history[i:i + 2] for i in range(0, len(history), 2)][-budget.history_turns:] if budget.history_turns else []
    dropped_turns = len(history) // 2 - len(turns) if history else 0

    def flat(selected: list[list[Message]]) -> list[Message]:
        return [message for turn in selected for message in turn]

    base = await backend.count_tokens(build_messages(question, flat(turns), []))
    while base > limit and turns:
        turns.pop(0)
        dropped_turns += 1
        base = await backend.count_tokens(build_messages(question, flat(turns), []))
    if base > limit:
        raise BudgetExceeded

    # Passages arrive best first. Keep them in order until the passage budget is spent, so the
    # lowest-ranked ones are the ones dropped.
    kept: list[Passage] = []
    spent = 0
    for number, passage in enumerate(passages, start=1):
        cost = await backend.count_text(f"[S{number}] {passage_heading(passage)}\n{passage.text}")
        if spent + cost > budget.passage_tokens:
            break
        kept.append(passage)
        spent += cost

    messages = build_messages(question, flat(turns), kept)
    total = await backend.count_tokens(messages)
    while total > limit and kept:
        kept.pop()
        messages = build_messages(question, flat(turns), kept)
        total = await backend.count_tokens(messages)
    return FittedPrompt(messages, kept, total, len(passages) - len(kept), dropped_turns)

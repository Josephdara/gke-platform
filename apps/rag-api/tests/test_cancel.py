"""A client that leaves mid-stream closes the upstream request and frees its admission slot."""

import asyncio
from types import SimpleNamespace

from prometheus_client import REGISTRY
import pytest

from rag_api.budget import Budget, fit_prompt
from rag_api.chat import stream_answer
from rag_api.conversations import MemoryConversationStore
from rag_api.limits import AdmissionLimiter

from conftest import PASSAGES
from fake_model import FakeModelServer


def cancelled_count():
    return REGISTRY.get_sample_value("rag_requests_total", {"status": "cancelled"}) or 0


async def open_stream(settings, model, logger):
    backend = model.backend()
    state = SimpleNamespace(settings=settings, backend=backend, admission=AdmissionLimiter(3), logger=logger,
                            conversations=MemoryConversationStore())
    conversation_id = await state.conversations.create("tester", "Why?")
    assert state.admission.try_acquire()
    budget = Budget(settings.context_tokens, settings.output_tokens, settings.passage_tokens, settings.history_turns)
    fitted = await fit_prompt("Why?", [], PASSAGES, backend, budget)
    return state, stream_answer(state, fitted, "request-1", asyncio.get_running_loop().time(), "tester", conversation_id)


@pytest.fixture
def logger(settings, log_stream):
    from rag_api.logging import create_logger
    return create_logger(settings, log_stream)


def test_closing_the_stream_closes_upstream(settings, logger):
    model = FakeModelServer(tokens=["one "] * 50, delay=0.01)

    async def scenario():
        state, stream = await open_stream(settings, model, logger)
        received = [await anext(stream), await anext(stream)]
        await stream.aclose()
        return state, received

    before = cancelled_count()
    state, received = asyncio.run(scenario())
    assert received[0].startswith("event: meta") and received[1].startswith("event: token")
    assert model.closed
    assert state.admission.active == 0
    assert cancelled_count() == before + 1


def test_cancelling_the_task_while_waiting_closes_upstream(settings, logger):
    model = FakeModelServer(mode="stall", fail_after=1)

    async def scenario():
        state, stream = await open_stream(settings, model, logger)
        received = []

        async def consume():
            async for event in stream:
                received.append(event)

        task = asyncio.create_task(consume())
        while len(received) < 2:
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return state, received

    before = cancelled_count()
    state, received = asyncio.run(scenario())
    assert not any(event.startswith(("event: done", "event: error")) for event in received)
    assert model.closed
    assert state.admission.active == 0
    assert cancelled_count() == before + 1

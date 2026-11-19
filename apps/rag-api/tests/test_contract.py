"""Checks the fake model server's assumptions against a real llama.cpp server.

Skipped unless RAG_API_CONTRACT_URL points at one, for example llama.cpp in Docker with the chat
model and --metrics. Run it whenever the llama.cpp image changes.
"""

import asyncio
import os
import re

import httpx
import pytest

from rag_api.inference import Finish, LlamaCppBackend, Token, create_model_client
from rag_api.prompt import Passage, build_messages

URL = os.environ.get("RAG_API_CONTRACT_URL")
pytestmark = pytest.mark.skipif(not URL, reason="RAG_API_CONTRACT_URL is not set")

MESSAGES = build_messages("What restarts a container?", [], [Passage("p", "Probes", "A failing liveness probe restarts the container.")])


def run(coroutine_factory):
    async def wrapper():
        client = create_model_client(URL, read_seconds=120)
        try:
            return await coroutine_factory(LlamaCppBackend(client, "assistant-chat"), client)
        finally:
            await client.aclose()
    return asyncio.run(wrapper())


async def processing(client: httpx.AsyncClient) -> float:
    text = (await client.get("/metrics")).text
    return float(re.search(r"^llamacpp:requests_processing (\S+)", text, re.M).group(1))


def test_stream_format_and_token_count_match_the_server():
    async def scenario(backend, client):
        counted = await backend.count_tokens(MESSAGES)
        events = [event async for event in backend.chat_stream(MESSAGES, max_tokens=16)]
        return counted, events

    counted, events = run(scenario)
    tokens = [e for e in events if isinstance(e, Token)]
    finish, = [e for e in events if isinstance(e, Finish)]
    assert tokens and isinstance(events[-1], Finish)
    assert finish.reason in ("stop", "length")
    assert finish.generated_tokens is not None and finish.generated_tokens <= 16
    # The server reports the prompt it processed; the template-aware count must match it.
    assert finish.prompt_tokens == counted


def test_closing_a_stream_frees_the_server_slot():
    async def scenario(backend, client):
        stream = backend.chat_stream(MESSAGES, max_tokens=300)
        for _ in range(3):
            await anext(stream)
        busy = await processing(client)
        await stream.aclose()
        for _ in range(50):
            if await processing(client) == 0:
                return busy, True
            await asyncio.sleep(0.1)
        return busy, False

    busy, freed = run(scenario)
    assert busy >= 1
    assert freed, "The server kept processing after the client closed the stream"

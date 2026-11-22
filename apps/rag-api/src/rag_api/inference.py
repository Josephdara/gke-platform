"""Inference adapter: one interface for chat model servers, with a llama.cpp implementation."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
import json
from typing import Protocol

import httpx

Message = dict[str, str]


class UpstreamError(Exception):
    """The model server failed, answered with an error, or sent a malformed stream."""


class ModelUnavailable(UpstreamError):
    """The model server could not be reached."""


@dataclass(frozen=True)
class Token:
    text: str


@dataclass(frozen=True)
class Finish:
    # The server's finish reason: "stop" for a natural end, "length" at the output limit.
    reason: str
    prompt_tokens: int | None = None
    generated_tokens: int | None = None
    timings: dict = field(default_factory=dict)


class InferenceBackend(Protocol):
    def chat_stream(self, messages: list[Message], max_tokens: int) -> AsyncIterator[Token | Finish]: ...

    async def count_tokens(self, messages: list[Message]) -> int: ...

    async def count_text(self, text: str) -> int: ...

    async def health(self) -> bool: ...

    def model_info(self) -> dict[str, str]: ...


def create_model_client(base_url: str, connect_seconds: float = 5, read_seconds: float = 60) -> httpx.AsyncClient:
    # Idle connections expire after 5 seconds, so a pooled connection does not reach a model
    # server Pod that has left the Service endpoints, and new connections spread across replicas.
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=httpx.Timeout(read_seconds, connect=connect_seconds),
        limits=httpx.Limits(keepalive_expiry=5),
        trust_env=False,
    )


class LlamaCppBackend:
    """llama.cpp server through its OpenAI-compatible chat route and its tokenizer routes."""

    def __init__(self, client: httpx.AsyncClient, alias: str):
        self.client = client
        self.alias = alias

    async def _post(self, path: str, body: dict) -> dict:
        try:
            response = await self.client.post(path, json=body)
        except httpx.TransportError as exc:
            raise ModelUnavailable(type(exc).__name__) from None
        if response.status_code != 200:
            raise UpstreamError(f"{path} returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError:
            raise UpstreamError(f"{path} returned invalid JSON") from None

    async def count_text(self, text: str) -> int:
        tokens = (await self._post("/tokenize", {"content": text})).get("tokens")
        if not isinstance(tokens, list):
            raise UpstreamError("/tokenize returned no tokens")
        return len(tokens)

    async def count_tokens(self, messages: list[Message]) -> int:
        # The server's own chat template adds role markers, so counting the rendered prompt
        # matches the prompt size the server reports for the same messages.
        prompt = (await self._post("/apply-template", {"messages": messages})).get("prompt")
        if not isinstance(prompt, str):
            raise UpstreamError("/apply-template returned no prompt")
        return await self.count_text(prompt)

    async def health(self) -> bool:
        try:
            response = await self.client.get("/health")
        except httpx.TransportError:
            return False
        return response.status_code == 200

    def model_info(self) -> dict[str, str]:
        return {"runtime": "llamacpp", "alias": self.alias}

    async def chat_stream(self, messages: list[Message], max_tokens: int) -> AsyncIterator[Token | Finish]:
        body = {
            "model": self.alias,
            "messages": messages,
            "stream": True,
            # The server treats its own output limit only as a default, so every request sets one.
            "max_tokens": max_tokens,
            # Greedy decoding keeps answers close to the passages, and lets an evaluation be repeated.
            "temperature": 0,
            "cache_prompt": True,
        }
        try:
            async with self.client.stream("POST", "/v1/chat/completions", json=body) as response:
                if response.status_code != 200:
                    raise UpstreamError(f"chat returned HTTP {response.status_code}")
                async for event in _sse_data(response):
                    if event == "[DONE]":
                        return
                    token, finish = _parse_chunk(event)
                    if token is not None:
                        yield token
                    if finish is not None:
                        yield finish
        except httpx.TransportError as exc:
            if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
                raise ModelUnavailable(type(exc).__name__) from None
            raise UpstreamError(type(exc).__name__) from None


async def _sse_data(response: httpx.Response) -> AsyncIterator[str]:
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            yield line[5:].strip()


def _parse_chunk(data: str) -> tuple[Token | None, Finish | None]:
    try:
        chunk = json.loads(data)
        choice = chunk["choices"][0] if chunk.get("choices") else {}
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise UpstreamError("chat stream sent a malformed chunk") from None
    if not isinstance(choice, dict):
        raise UpstreamError("chat stream sent a malformed chunk")
    content = (choice.get("delta") or {}).get("content")
    token = Token(content) if isinstance(content, str) and content else None
    reason = choice.get("finish_reason")
    finish = None
    if reason:
        timings = chunk.get("timings") or {}
        usage = chunk.get("usage") or {}
        prompt = usage.get("prompt_tokens")
        if prompt is None and "prompt_n" in timings:
            prompt = timings.get("prompt_n", 0) + timings.get("cache_n", 0)
        generated = usage.get("completion_tokens", timings.get("predicted_n"))
        finish = Finish(reason=reason, prompt_tokens=prompt, generated_tokens=generated, timings=timings)
    return token, finish

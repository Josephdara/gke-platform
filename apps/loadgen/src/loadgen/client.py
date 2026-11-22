"""A signed-in client for the assistant: one question in, one recorded sample out."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import re
import time

import httpx

CITATION = re.compile(r"\[(S\d{1,3})\]")


class SignInFailed(Exception):
    """The username or password was refused, or the site did not answer."""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass
class Sample:
    """One request. outcome is complete or length (an answer), error:<reason> (the stream's own
    error event), http:<status> (refused before streaming), cut (the stream ended without a
    terminal event), or transport:<error> (no response at all)."""
    question: str
    started_at: str
    outcome: str = "cut"
    ttft_s: float | None = None
    total_s: float | None = None
    request_id: str | None = None
    conversation_id: str | None = None
    mode: str | None = None
    prompt_version: str | None = None
    sources: list[dict] = field(default_factory=list)
    valid_citations: list[str] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)
    completion_tokens: int | None = None
    # Seconds the server asked the caller to wait, from Retry-After on a 429.
    retry_after_s: int | None = None
    output_chars: int = 0
    answer: str | None = None

    @property
    def answered(self) -> bool:
        return self.outcome in ("complete", "length")


async def sse_events(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, dict]]:
    """Server-sent events as (event, data) pairs; an event ends at a blank line."""
    event, data = None, []
    async for line in lines:
        if not line:
            if event is not None:
                yield event, json.loads("\n".join(data))
            event, data = None, []
        elif line.startswith("event: "):
            event = line[len("event: "):]
        elif line.startswith("data: "):
            data.append(line[len("data: "):])


class Assistant:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None, timeout: float = 180):
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(timeout, connect=10))
        # rag-api accepts state changes only with its own Origin and this header.
        self.headers = {"Origin": self.base_url, "X-Assistant-Client": "1"}

    async def sign_in(self, username: str, password: str) -> None:
        try:
            response = await self.client.post("/api/session", json={"username": username, "password": password},
                                              headers=self.headers)
        except httpx.HTTPError as exc:
            raise SignInFailed(type(exc).__name__) from None
        if response.status_code != 204:
            raise SignInFailed(f"sign-in returned HTTP {response.status_code}")

    async def status(self) -> dict:
        response = await self.client.get("/api/status")
        response.raise_for_status()
        return response.json()

    async def ask(self, question: str, keep_answer: bool = False) -> Sample:
        """Asks in a new conversation and records how the stream went. Never raises for the
        request itself: every failure is an outcome."""
        sample = Sample(question, now())
        started = time.monotonic()
        parts: list[str] = []
        streaming = False
        try:
            async with self.client.stream("POST", "/api/chat", json={"question": question}, headers=self.headers) as response:
                sample.request_id = response.headers.get("x-request-id")
                if response.status_code != 200:
                    sample.outcome = f"http:{response.status_code}"
                    retry_after = response.headers.get("retry-after", "")
                    sample.retry_after_s = int(retry_after) if retry_after.isdigit() else None
                else:
                    streaming = True
                    async for event, data in sse_events(response.aiter_lines()):
                        if event == "meta":
                            sample.conversation_id = data.get("conversationId")
                            sample.mode = data.get("mode")
                            sample.prompt_version = data.get("promptVersion")
                            sample.sources = data.get("sources", [])
                        elif event == "token":
                            if sample.ttft_s is None:
                                sample.ttft_s = round(time.monotonic() - started, 3)
                            parts.append(data["text"])
                        elif event == "done":
                            sample.outcome = data["status"]
                            sample.valid_citations = data["citations"]["valid"]
                            sample.invalid_citations = data["citations"]["invalid"]
                            sample.completion_tokens = data["usage"]["completionTokens"]
                        elif event == "error":
                            sample.outcome = f"error:{data['reason']}"
        except httpx.HTTPError as exc:
            # A failure after the stream started is a cut stream; before it, no response at all.
            if not streaming:
                sample.outcome = f"transport:{type(exc).__name__}"
        sample.total_s = round(time.monotonic() - started, 3)
        answer = "".join(parts)
        sample.output_chars = len(answer)
        if keep_answer:
            sample.answer = answer
        return sample

    async def close(self) -> None:
        await self.client.aclose()

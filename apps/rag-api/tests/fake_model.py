"""A fake llama.cpp server for tests, served through httpx's mock transport.

It speaks the same routes and stream format as llama.cpp, so the real adapter runs against it,
and it can stream, fail mid-stream, stall, end without a finish reason, refuse, or be unreachable.
"""

import asyncio
import json

import httpx

from rag_api.inference import LlamaCppBackend


def word_count(text: str) -> int:
    return len(text.split())


class RecordingStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        async for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class FakeModelServer:
    def __init__(self, tokens=("Pods ", "restart ", "[S1]."), mode="normal", fail_after=1,
                 delay=0.0, finish_reason="stop", healthy=True, first_delay=0.0):
        self.tokens = list(tokens)
        self.mode = mode
        self.fail_after = fail_after
        self.delay = delay
        self.finish_reason = finish_reason
        self.healthy = healthy
        self.first_delay = first_delay
        self.chat_bodies: list[dict] = []
        self.streams: list[RecordingStream] = []

    @property
    def closed(self) -> bool:
        return bool(self.streams) and all(stream.closed for stream in self.streams)

    def backend(self, alias="assistant-chat") -> LlamaCppBackend:
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.handle), base_url="http://model")
        return LlamaCppBackend(client, alias)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        if self.mode == "unreachable":
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        if path == "/health":
            return httpx.Response(200 if self.healthy else 503, json={"status": "ok"})
        body = json.loads(request.content or b"{}")
        if path == "/tokenize":
            return httpx.Response(200, json={"tokens": list(range(word_count(body["content"])))})
        if path == "/apply-template":
            prompt = " ".join(f"<{m['role']}> {m['content']}" for m in body["messages"])
            return httpx.Response(200, json={"prompt": prompt})
        if path == "/v1/chat/completions":
            self.chat_bodies.append(body)
            if self.mode == "http_error":
                return httpx.Response(500, json={"error": "server error"})
            stream = RecordingStream(self.events())
            self.streams.append(stream)
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)
        return httpx.Response(404)

    async def events(self):
        if self.first_delay:
            await asyncio.sleep(self.first_delay)
        for index, token in enumerate(self.tokens):
            if index == self.fail_after and self.mode == "fail_mid":
                raise httpx.ReadError("connection reset")
            if index == self.fail_after and self.mode == "stall":
                await asyncio.sleep(3600)
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk({"delta": {"content": token}, "finish_reason": None})
        if self.mode == "no_finish":
            return
        yield chunk({"delta": {}, "finish_reason": self.finish_reason},
                    timings={"prompt_n": 40, "cache_n": 2, "predicted_n": len(self.tokens)})
        yield b"data: [DONE]\n\n"


def chunk(choice: dict, **extra) -> bytes:
    data = {"choices": [{"index": 0, **choice}], "object": "chat.completion.chunk", **extra}
    return f"data: {json.dumps(data)}\n\n".encode()

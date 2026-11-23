"""A fake Text Embeddings Inference server: one token per word, deterministic unit vectors."""

import hashlib
import json
import math

import httpx

from ingest.embed import TeiClient


def vector(text: str, dimensions: int = 384) -> list[float]:
    seed = hashlib.sha256(text.encode()).digest()
    raw = [((seed[i % 32] + i * 7) % 255) / 255 - 0.5 for i in range(dimensions)]
    norm = math.sqrt(sum(v * v for v in raw))
    return [v / norm for v in raw]


class FakeTei:
    def __init__(self, dimensions=384, fail=False, busy=0):
        self.dimensions = dimensions
        self.fail = fail
        # Answers this many requests with 429 before serving, like a full concurrency limit.
        self.busy = busy
        self.embed_calls = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if self.fail:
            return httpx.Response(503)
        if self.busy:
            self.busy -= 1
            return httpx.Response(429, headers={"retry-after": "2"})
        if request.url.path == "/tokenize":
            return httpx.Response(200, json=[[{"id": n} for n, _ in enumerate(text.split())] for text in body["inputs"]])
        if request.url.path == "/embed":
            self.embed_calls += 1
            return httpx.Response(200, json=[vector(text, self.dimensions) for text in body["inputs"]])
        return httpx.Response(404)

    def client(self, batch=16, dimensions=384, sleep=lambda seconds: None) -> TeiClient:
        http = httpx.Client(transport=httpx.MockTransport(self.handle), base_url="http://tei")
        return TeiClient(http, "http://tei", dimensions, batch, sleep)

"""Text Embeddings Inference client: token counts with the model's tokenizer, and embeddings."""

import time

import httpx

# TEI's default limit on inputs per request.
MAX_BATCH = 32
# A 429 means the server's concurrency limit is full: wait and retry, doubling the wait each time,
# or for as long as Retry-After asks, at most 30 seconds.
RETRIES = 5
FIRST_WAIT_SECONDS = 1.0


class EmbeddingError(Exception):
    """The embeddings server failed or returned vectors of the wrong size."""


class TeiClient:
    def __init__(self, client: httpx.Client, base_url: str, dimensions: int, batch: int, sleep=time.sleep):
        self.client = client
        self.sleep = sleep
        self.base_url = base_url
        self.dimensions = dimensions
        self.batch = min(batch, MAX_BATCH)

    def _post(self, path: str, body: dict):
        wait = FIRST_WAIT_SECONDS
        for attempt in range(RETRIES + 1):
            try:
                response = self.client.post(f"{self.base_url}{path}", json=body)
            except httpx.HTTPError as exc:
                raise EmbeddingError(type(exc).__name__) from None
            if response.status_code != 429 or attempt == RETRIES:
                break
            asked = response.headers.get("retry-after", "")
            self.sleep(min(float(asked) if asked.isdigit() else wait, 30.0))
            wait *= 2
        if response.status_code != 200:
            raise EmbeddingError(f"{path} returned HTTP {response.status_code}")
        return response.json()

    def count(self, texts: list[str]) -> list[int]:
        counts: list[int] = []
        for start in range(0, len(texts), MAX_BATCH):
            batch = texts[start:start + MAX_BATCH]
            tokens = self._post("/tokenize", {"inputs": batch, "add_special_tokens": False})
            if not isinstance(tokens, list) or len(tokens) != len(batch):
                raise EmbeddingError("/tokenize returned the wrong number of results")
            counts.extend(len(item) for item in tokens)
        return counts

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch):
            batch = texts[start:start + self.batch]
            result = self._post("/embed", {"inputs": batch, "truncate": True, "normalize": True})
            if not isinstance(result, list) or len(result) != len(batch):
                raise EmbeddingError("/embed returned the wrong number of vectors")
            for vector in result:
                if not isinstance(vector, list) or len(vector) != self.dimensions:
                    raise EmbeddingError(f"/embed returned a vector that is not {self.dimensions} long")
            vectors.extend(result)
        return vectors

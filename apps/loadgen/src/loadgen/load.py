"""Fixed-concurrency load: each worker asks one question after another until the duration ends."""

import asyncio
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
import itertools
import math
import time

from .client import Assistant, Sample

REFUSED_PAUSE_S = 2


async def run_load(assistant: Assistant, questions: list[str], concurrency: int, duration_s: float,
                   on_sample: Callable[[Sample], None]) -> list[Sample]:
    """No request starts after the duration ends, but every started request runs to its end, so
    the load generator never cuts a stream itself."""
    samples: list[Sample] = []
    order = itertools.cycle(questions)
    deadline = time.monotonic() + duration_s

    async def worker() -> None:
        while time.monotonic() < deadline:
            sample = await assistant.ask(next(order))
            samples.append(sample)
            on_sample(sample)
            # A refused request is retried only after the wait the server asked for, and any
            # other failure after a short pause, so a failing server is never hammered.
            if not sample.answered:
                wait = min(sample.retry_after_s or REFUSED_PAUSE_S, max(0.0, deadline - time.monotonic()))
                await asyncio.sleep(wait)

    await asyncio.gather(*(worker() for _ in range(concurrency)))
    return samples


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile; None without values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def summarize(samples: list[Sample]) -> dict:
    answered = [s for s in samples if s.answered]
    ttft = [s.ttft_s for s in answered if s.ttft_s is not None]
    total = [s.total_s for s in answered if s.total_s is not None]
    return {
        "requests": len(samples),
        "answered": len(answered),
        "outcomes": dict(sorted(Counter(s.outcome for s in samples).items())),
        "modes": dict(sorted(Counter(s.mode or "none" for s in samples).items())),
        "firstStart": min((s.started_at for s in samples), default=None),
        "lastStart": max((s.started_at for s in samples), default=None),
        # Answered requests only. With few samples, p95 is close to the maximum.
        "ttftSeconds": {"p50": percentile(ttft, 50), "p95": percentile(ttft, 95), "count": len(ttft)},
        "totalSeconds": {"p50": percentile(total, 50), "p95": percentile(total, 95), "count": len(total)},
        "failed": [{"startedAt": s.started_at, "outcome": s.outcome, "requestId": s.request_id}
                   for s in samples if not s.answered],
    }


def sample_line(sample: Sample) -> dict:
    return {key: value for key, value in asdict(sample).items() if key != "answer"}

"""Per-replica admission limit and per-session rate limit."""

from collections import deque
import math
import time


class AdmissionLimiter:
    """Caps the generations one replica runs at once. It never waits: a full replica refuses."""

    def __init__(self, limit: int):
        self.limit = limit
        self.active = 0

    def try_acquire(self) -> bool:
        if self.active >= self.limit:
            return False
        self.active += 1
        return True

    def release(self) -> None:
        self.active = max(0, self.active - 1)


class RateLimiter:
    """Sliding one-minute window per key. Counted per replica, so it guards against abuse, not a quota."""

    WINDOW = 60.0

    def __init__(self, per_minute: int, clock=time.monotonic):
        self.per_minute = per_minute
        self.clock = clock
        self.calls: dict[str, deque[float]] = {}

    def check(self, key: str) -> int:
        """Records a call and returns 0 when allowed, or the seconds to wait when refused."""
        now = self.clock()
        calls = self.calls.setdefault(key, deque())
        while calls and now - calls[0] >= self.WINDOW:
            calls.popleft()
        if len(calls) >= self.per_minute:
            return max(1, math.ceil(self.WINDOW - (now - calls[0])))
        calls.append(now)
        # Drop idle keys so the table does not grow with every caller ever seen.
        if len(self.calls) > 10000:
            self.calls = {k: v for k, v in self.calls.items() if v and now - v[-1] < self.WINDOW}
        return 0

"""Provider rate-limit helpers: header parsing and a rolling 60 s pacing window."""

import re
import time
from collections import deque

WINDOW = 60.0
_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_UNIT = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


def parse_duration(text):
    """Seconds from '7.66s', '1m2.5s', '450ms' or a bare number; None if unusable."""
    text = (text or "").strip().lower()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    parts = _PART.findall(text)
    if not parts or "".join(n + u for n, u in parts) != text:
        return None
    return sum(float(n) * _UNIT[u] for n, u in parts)


def retry_wait(headers, attempt, max_wait):
    """Seconds to wait after a 429: retry-after, else Groq reset headers, else backoff."""
    wait = parse_duration(headers.get("retry-after"))
    if wait is None:
        resets = [
            parse_duration(headers.get(h))
            for h in ("x-ratelimit-reset-tokens", "x-ratelimit-reset-requests")
        ]
        resets = [r for r in resets if r is not None]
        wait = max(resets) if resets else None
    if wait is None:
        wait = 5.0 * 2**attempt
    return min(wait, max_wait)


class Pacer:
    """Rolling-window request/token limiter. A limit of 0 disables that dimension."""

    def __init__(self, tpm, rpm, sleep=time.sleep, monotonic=time.monotonic):
        self.tpm, self.rpm = tpm, rpm
        self.sleep, self.monotonic = sleep, monotonic
        self.window = deque()  # [timestamp, tokens]; tokens 0 until response usage

    @property
    def enabled(self):
        return bool(self.tpm or self.rpm)

    def oversized(self, estimate):
        return bool(self.tpm) and estimate > self.tpm

    def wait_needed(self, estimate):
        """Seconds until the request fits; 0 if it fits now or never could."""
        now = self.monotonic()
        while self.window and now - self.window[0][0] >= WINDOW:
            self.window.popleft()
        tokens = sum(t for _, t in self.window)
        count = len(self.window)
        check_tpm = bool(self.tpm) and not self.oversized(estimate)

        def fits():
            return (not check_tpm or tokens + estimate <= self.tpm) and (
                not self.rpm or count + 1 <= self.rpm
            )

        released = None
        for ts, tok in self.window:
            if fits():
                break
            tokens -= tok
            count -= 1
            released = ts
        if released is None or not fits():
            return 0.0
        return max(released + WINDOW - now, 0.0)

    def acquire(self, estimate):
        """Block via the injected sleep until allowed; returns seconds slept."""
        slept = 0.0
        for _ in range(100):
            if not self.enabled:
                break
            wait = self.wait_needed(estimate)
            if wait <= 0:
                break
            wait = min(wait + 0.01, WINDOW)
            self.sleep(wait)
            slept += wait
        return slept

    def started(self):
        entry = [self.monotonic(), 0]
        self.window.append(entry)
        return entry

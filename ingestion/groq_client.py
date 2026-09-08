"""Groq API key rotation pool for the ingestion pipeline.

Python port of ../src/lib/groq/client.ts — keep the retry/rotation
behavior in sync between the two.

Verified empirically (2026-09-08) rather than assumed: of the 6 keys,
4 belong to 4 distinct Groq organizations and the other 2 share a
5th org — so this pool is backed by 5 independent daily quotas, not
one shared pool and not 6 separate ones. Rotating across keys on a
429 is therefore the right strategy (an earlier version of this file
incorrectly assumed one org shared by all 6 keys, based on reading a
single error message without checking whether other keys resolved to
different orgs — they do).

- 400 (malformed request) and 413 (request too large for the model's
  per-request limit) are properties of the request itself — no key
  fixes either, so these propagate immediately.
- 401/403 (bad/revoked key), 404, and 429 (rate limit) are per-key
  (really per-org) — rotating to the next key is the correct response.
- On a 429, Groq reports how long until that key's limit resets
  ("Please try again in Xh Ym Z.ZZZs" or similar) — that's parsed and
  used as the actual cooldown instead of a flat guess, since a
  per-minute limit and a tokens-per-day limit need very different
  wait times (seconds vs. hours). If every key wants that long, this
  raises immediately with the shortest real wait time rather than
  sleeping for it — a multi-hour block belongs in the caller's
  hands, not silently inside this library.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from groq import Groq

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env.local"
load_dotenv(_ENV_PATH)

_KEY_PATTERN = re.compile(r"^GROQ_API_KEY(_\d+)?$")
_DEFAULT_COOLDOWN_SECONDS = 30.0

# Matches Groq's "Please try again in 4h15m24.768s" / "2m52.8s" / "577ms" / "45s"
_RETRY_AFTER_PATTERN = re.compile(
    r"try again in\s+(?:(\d+)h)?\s*(?:(\d+)m(?!s))?\s*(?:([\d.]+)s)?\s*(?:([\d.]+)ms)?",
    re.IGNORECASE,
)


def _parse_retry_after_seconds(message: str) -> float | None:
    match = _RETRY_AFTER_PATTERN.search(message)
    if not match or not any(match.groups()):
        return None
    hours, minutes, seconds, millis = match.groups()
    total = 0.0
    if hours:
        total += int(hours) * 3600
    if minutes:
        total += int(minutes) * 60
    if seconds:
        total += float(seconds)
    if millis:
        total += float(millis) / 1000
    return total if total > 0 else None


@dataclass
class _KeyState:
    key: str
    client: Groq
    cooldown_until: float = field(default=0.0)


class GroqKeyPool:
    def __init__(self) -> None:
        keys = [
            value
            for name, value in os.environ.items()
            if _KEY_PATTERN.match(name) and value
        ]
        if not keys:
            raise RuntimeError(
                "No Groq API keys found. Set GROQ_API_KEY / GROQ_API_KEY_2 / ... "
                f"in {_ENV_PATH}"
            )
        self._states = [_KeyState(key=k, client=Groq(api_key=k)) for k in keys]
        self._cursor = 0

    def _next_candidate(self) -> _KeyState | None:
        now = time.time()
        n = len(self._states)
        for i in range(n):
            state = self._states[(self._cursor + i) % n]
            if state.cooldown_until <= now:
                self._cursor = (self._cursor + i + 1) % n
                return state
        return None

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        status = getattr(error, "status_code", None) or getattr(error, "status", None)
        if status is None:
            return True  # network errors carry no status — treat as retryable
        # 400 (malformed request) and 413 (request too large for the
        # model's per-request token limit) are properties of the
        # request itself — a different key won't fix either one.
        return status not in (400, 413)

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        reasoning_effort: str | None = None,
        json_mode: bool = False,
    ) -> str:
        last_error: Exception | None = None

        for _ in range(len(self._states)):
            state = self._next_candidate()
            if state is None:
                break  # every key is cooling down

            try:
                response = state.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    reasoning_effort=reasoning_effort,
                    response_format={"type": "json_object"} if json_mode else None,
                )
                return response.choices[0].message.content or ""
            except Exception as error:  # noqa: BLE001 — inspect any SDK exception
                last_error = error
                if not self._is_retryable(error):
                    raise
                retry_after = _parse_retry_after_seconds(str(error))
                state.cooldown_until = time.time() + (retry_after or _DEFAULT_COOLDOWN_SECONDS)

        soonest_wait = min(state.cooldown_until - time.time() for state in self._states)
        raise RuntimeError(
            f"All {len(self._states)} Groq API keys are rate-limited. Soonest available "
            f"in {max(0.0, soonest_wait):.0f}s. Last error: {last_error}"
        )


_pool: GroqKeyPool | None = None


def get_pool() -> GroqKeyPool:
    global _pool
    if _pool is None:
        _pool = GroqKeyPool()
    return _pool

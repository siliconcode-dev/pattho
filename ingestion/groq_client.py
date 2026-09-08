"""Groq API key rotation pool for the ingestion pipeline.

Python port of ../src/lib/groq/client.ts — keep the retry/rotation
behavior in sync between the two, modulo one deliberate divergence: this
account's rate/size limits (observed: 8,000 TPM on openai/gpt-oss-120b)
are enforced per-organization, shared across every key, not per-key.
That changes what "retry across keys" actually means here:

- 400 (malformed request) and 413 (request too large for the model's
  per-request limit) are properties of the request itself — no key
  fixes either, so these propagate immediately.
- 401/403 (bad/revoked key) and 404 are genuinely per-key — rotating
  works as intended.
- 429 (rate limit) is per-organization here, so rotating to another key
  usually just hits the same exhausted shared budget. If a full pass
  finds every key cooling down, that's treated as a shared-budget
  exhaustion: wait for the earliest cooldown to clear and try again
  (bounded to a few rounds) rather than failing immediately.
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
_COOLDOWN_SECONDS = 30.0


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

        # This account's rate limit is enforced per-organization, shared
        # across every key in the pool - rotating keys does nothing for a
        # genuine 429, only for a dead/revoked individual key. So if a
        # full pass finds every key cooling down, that's most likely a
        # shared-budget exhaustion, not 6 independently broken keys -
        # wait it out and try again a bounded number of times instead of
        # failing immediately.
        for _round in range(3):
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
                    state.cooldown_until = time.time() + _COOLDOWN_SECONDS
            else:
                continue  # inner loop completed without a `break` -> no candidate was ever None

            # Hit the `break` above (all keys cooling down) - wait for the
            # earliest one to clear, then start another round.
            soonest = min(state.cooldown_until for state in self._states)
            wait_seconds = max(0.0, soonest - time.time())
            if wait_seconds > 0:
                time.sleep(wait_seconds)

        raise RuntimeError(
            f"All Groq API keys exhausted or on cooldown after retrying. Last error: {last_error}"
        )


_pool: GroqKeyPool | None = None


def get_pool() -> GroqKeyPool:
    global _pool
    if _pool is None:
        _pool = GroqKeyPool()
    return _pool

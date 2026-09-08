"""Groq API key rotation pool for the ingestion pipeline.

Python port of ../src/lib/groq/client.ts — keep the retry/rotation
behavior in sync between the two. In particular: a request failure is
only NOT retried across keys when it's a 400 (malformed request/model
name), since a different key won't fix that. Everything else (401/403
bad-or-revoked key, 404, 429 rate limit, 5xx, network errors) is
per-key or transient, so the pool should route around it.
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
        return status != 400

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
                state.cooldown_until = time.time() + _COOLDOWN_SECONDS

        raise RuntimeError(
            f"All Groq API keys exhausted or on cooldown. Last error: {last_error}"
        )


_pool: GroqKeyPool | None = None


def get_pool() -> GroqKeyPool:
    global _pool
    if _pool is None:
        _pool = GroqKeyPool()
    return _pool

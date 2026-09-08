"""Check remaining daily Groq quota across all configured keys.

Run this before a big ingestion batch to see how much headroom is
actually available, instead of discovering it mid-run. The 6 keys in
.env.local aren't one pool — as of 2026-09-08, 4 belong to 4 distinct
Groq orgs and the other 2 share a 5th, so this reports up to 5
independent daily budgets (grouped by org, since two keys on the same
org share one number).

IMPORTANT: Groq only reveals remaining DAILY tokens when a request
actually EXCEEDS them (in the error message) — a successful response's
headers only show the per-MINUTE window, which resets in under a
second and is rarely the real bottleneck once requests are
batch-sized. So a cheap 1-token probe only proves a key still
authenticates; it tells you nothing about real daily headroom. Use
--big to spend a real ~20k-token probe per key instead, which will
correctly report "OK" (found headroom) or "BLOCKED" (with the actual
used/limit numbers) for the daily quota — but that itself costs up to
~20k tokens per key that answers OK, so don't run it more than you
need to.

Usage:
    python check_quota.py         # cheap: per-minute health check only
    python check_quota.py --big   # expensive: real daily-headroom check
"""

from __future__ import annotations

import os
import re
import sys

from dotenv import load_dotenv
from groq import Groq

load_dotenv("../.env.local")

_KEY_PATTERN = re.compile(r"^GROQ_API_KEY(_\d+)?$")
_PROBE_MODEL = "openai/gpt-oss-120b"
_BIG_PROBE_TEXT = "The quick brown fox jumps over the lazy dog. " * 1800


def main() -> None:
    big = "--big" in sys.argv
    keys = [
        (name, value)
        for name, value in os.environ.items()
        if _KEY_PATTERN.match(name) and value
    ]
    if not keys:
        print("No GROQ_API_KEY* found in .env.local")
        return

    mode = "daily-headroom (expensive)" if big else "per-minute health (cheap)"
    print(f"Checking {len(keys)} key(s) — {mode}...\n")
    seen_orgs: dict[str, list[str]] = {}

    for name, key in keys:
        client = Groq(api_key=key)
        content = f"Count the words in this text: {_BIG_PROBE_TEXT}" if big else "hi"
        max_tokens = 10 if big else 1
        try:
            resp = client.chat.completions.with_raw_response.create(
                model=_PROBE_MODEL,
                messages=[{"role": "user", "content": content}],
                max_tokens=max_tokens,
            )
            headers = resp.headers
            remaining_tokens = headers.get("x-ratelimit-remaining-tokens", "?")
            reset_tokens = headers.get("x-ratelimit-reset-tokens", "?")
            note = "daily headroom confirmed" if big else "per-minute only, daily unknown"
            print(
                f"{name}: OK ({note}; per-minute remaining_tokens={remaining_tokens}, "
                f"resets in {reset_tokens})"
            )
        except Exception as error:  # noqa: BLE001
            msg = str(error)
            org_match = re.search(r"organization `(org_[a-zA-Z0-9]+)`", msg)
            used_match = re.search(r"Used (\d+)", msg)
            limit_match = re.search(r"Limit (\d+)", msg)
            retry_match = re.search(r"try again in ([^.]+\.?\d*s)", msg)
            org = org_match.group(1) if org_match else "unknown"
            used = used_match.group(1) if used_match else "?"
            limit = limit_match.group(1) if limit_match else "?"
            retry = retry_match.group(1) if retry_match else "?"
            print(f"{name}: BLOCKED org={org} used={used}/{limit} retry_in={retry}")
            seen_orgs.setdefault(org, []).append(name)

    if seen_orgs:
        print(f"\n{len(seen_orgs)} distinct org(s) currently blocked (out of {len(keys)} keys):")
        for org, names in seen_orgs.items():
            print(f"  {org}: {', '.join(names)}")


if __name__ == "__main__":
    main()

"""Stage 3 — LLM cleanup + structural segmentation.

Feeds one chapter's raw page-by-page text (native-extracted and/or
OCR'd, in reading order) through Groq to: (a) clean up OCR noise /
garbled Bangla+math, (b) segment it into topic -> sub-topic ->
worked-example, per Build_plan.md's chapter -> topic -> sub-topic ->
worked-example hierarchy. Chapter itself is supplied by the caller
(derived from the source PDF's filename, one PDF per chapter) rather
than detected by the model — a chapter boundary is a fact about the
file, not something worth spending model judgment on.

A full chapter's OCR'd text can easily exceed this Groq account's
per-request token limit (observed: 8,000 TPM cap on
`openai/gpt-oss-120b`, while a single 49-page chapter needed ~49,000).
Rather than guess a fixed pages-per-call batch size that might still
be too large for a denser chapter, `structure_chapter` recursively
halves the page batch on a "request too large" response and retries
each half — this adapts to whatever the actual limit turns out to be,
at the cost of an occasional topic/subtopic getting split across a
batch seam (an acceptable v1 tradeoff, not a correctness issue).

No explicit chain-of-thought prompting per Claude.md — reasoning_effort
is the tuning knob, not "think step by step" instructions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from groq_client import get_pool

STRUCTURE_MODEL = "openai/gpt-oss-120b"

_SYSTEM_PROMPT = """You are cleaning and structuring OCR'd text from part of one chapter of a Bangladeshi HSC Physics textbook.

The input is raw page text (Bangla, English, or mixed) that may contain OCR noise,
garbled math notation, and broken line breaks from page extraction. It may be a
partial excerpt of the chapter rather than the whole thing.

Your job:
1. Clean up obvious OCR errors while preserving the original meaning and language
   (do not translate Bangla to English or vice versa).
2. Reconstruct math notation as plain-text approximations (e.g. "v^2 = u^2 + 2as")
   where the OCR output is clearly a garbled formula — do not invent physics that
   isn't in the source text.
3. Segment the cleaned text into topic -> sub-topic -> worked example, based on
   headings, numbering, and content shifts visible in the text. Do not invent a
   chapter field — the caller already knows the chapter.

Respond with a JSON object of the form {"chunks": [...]}, where each array
element is:
{
  "topic": string,
  "subtopic": string | null,
  "chunk_type": "narrative" | "worked_example",
  "text": string
}"""


@dataclass
class StructuredChunk:
    topic: str
    subtopic: str | None
    chunk_type: str
    text: str


def _should_split_and_retry(error: Exception) -> bool:
    if isinstance(error, ValueError):
        # Our own shape-validation failure (see _structure_batch) — the
        # model produced syntactically valid but structurally wrong
        # JSON (e.g. a double-encoded "chunks" string). Same remedy as
        # the Groq-reported cases: smaller/different retry, then skip.
        return True

    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    if status == 413:
        return True  # request itself too large for the per-request token limit
    if status == 400:
        # This account's output-token ceiling is tight enough that a
        # batch's structured-JSON completion can get truncated
        # mid-generation even when the request itself was accepted —
        # Groq reports this as 400 'json_validate_failed'. Smaller
        # input -> smaller expected output -> less likely to truncate.
        body = getattr(error, "body", None) or {}
        code = (body.get("error") or {}).get("code") if isinstance(body, dict) else None
        return code == "json_validate_failed"
    return False


def _structure_batch(batch_text: str, reasoning_effort: str = "medium") -> list[StructuredChunk]:
    pool = get_pool()
    raw = pool.chat(
        model=STRUCTURE_MODEL,
        reasoning_effort=reasoning_effort,
        json_mode=True,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": batch_text},
        ],
    )

    try:
        parsed = json.loads(raw)["chunks"]
        if isinstance(parsed, str):
            # Some completions double-encode: {"chunks": "[{...}]"}
            # instead of {"chunks": [{...}]}. Unwrap it once.
            parsed = json.loads(parsed)
        if not isinstance(parsed, list):
            raise ValueError(f"'chunks' was {type(parsed).__name__}, expected a list")

        return [
            StructuredChunk(
                topic=item["topic"],
                subtopic=item.get("subtopic"),
                chunk_type=item["chunk_type"],
                text=item["text"],
            )
            for item in parsed
        ]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ValueError(
            f"Structuring pass did not return the expected JSON shape: {error}\n"
            f"Raw output: {raw[:500]}"
        ) from error


def structure_chapter(page_texts: list[str]) -> list[StructuredChunk]:
    """Structures a chapter's pages, splitting into smaller batches and
    retrying if a batch is too large (or its expected output too long)
    for the model's per-request limits. `page_texts` is one string per
    page, in reading order.
    """
    if not page_texts:
        return []

    batch_text = "\n\n".join(page_texts)

    try:
        return _structure_batch(batch_text)
    except Exception as error:  # noqa: BLE001 — only split on the specific too-large case
        if not _should_split_and_retry(error):
            raise

        if len(page_texts) > 1:
            midpoint = len(page_texts) // 2
            print(
                f"    (batch of {len(page_texts)} pages too large, splitting into "
                f"{midpoint} + {len(page_texts) - midpoint})"
            )
            first_half = structure_chapter(page_texts[:midpoint])
            second_half = structure_chapter(page_texts[midpoint:])
            return first_half + second_half

        # Single page, still too large/truncating — one last try with
        # lower reasoning effort (leaves more room for the actual
        # completion), then give up on this page rather than crashing
        # the whole chapter's ingestion over one pathological page.
        try:
            print("    (single page still failing, retrying with reasoning_effort=low)")
            return _structure_batch(batch_text, reasoning_effort="low")
        except Exception as retry_error:  # noqa: BLE001
            if not _should_split_and_retry(retry_error):
                raise
            print("    (single page still failing after retry, skipping it)")
            return []

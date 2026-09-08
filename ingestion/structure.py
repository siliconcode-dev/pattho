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


def _is_request_too_large(error: Exception) -> bool:
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    return status == 413


def _structure_batch(batch_text: str) -> list[StructuredChunk]:
    pool = get_pool()
    raw = pool.chat(
        model=STRUCTURE_MODEL,
        reasoning_effort="medium",
        json_mode=True,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": batch_text},
        ],
    )

    try:
        parsed = json.loads(raw)["chunks"]
    except (json.JSONDecodeError, KeyError) as error:
        raise ValueError(
            f"Structuring pass did not return the expected JSON shape: {error}\n"
            f"Raw output: {raw[:500]}"
        ) from error

    return [
        StructuredChunk(
            topic=item["topic"],
            subtopic=item.get("subtopic"),
            chunk_type=item["chunk_type"],
            text=item["text"],
        )
        for item in parsed
    ]


def structure_chapter(page_texts: list[str]) -> list[StructuredChunk]:
    """Structures a chapter's pages, splitting into smaller batches and
    retrying if a batch is too large for the model's per-request token
    limit. `page_texts` is one string per page, in reading order.
    """
    if not page_texts:
        return []

    batch_text = "\n\n".join(page_texts)

    try:
        return _structure_batch(batch_text)
    except Exception as error:  # noqa: BLE001 — only split on the specific too-large case
        if not _is_request_too_large(error) or len(page_texts) == 1:
            raise

        midpoint = len(page_texts) // 2
        print(
            f"    (batch of {len(page_texts)} pages too large for the model's "
            f"per-request limit, splitting into {midpoint} + {len(page_texts) - midpoint})"
        )
        first_half = structure_chapter(page_texts[:midpoint])
        second_half = structure_chapter(page_texts[midpoint:])
        return first_half + second_half

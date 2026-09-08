"""Stage 3 — LLM cleanup + structural segmentation.

Feeds one chapter's raw page-by-page text (native-extracted and/or
OCR'd, in reading order) through Groq to: (a) clean up OCR noise /
garbled Bangla+math, (b) segment it into topic -> sub-topic ->
worked-example, per Build_plan.md's chapter -> topic -> sub-topic ->
worked-example hierarchy. Chapter itself is supplied by the caller
(derived from the source PDF's filename, one PDF per chapter) rather
than detected by the model — a chapter boundary is a fact about the
file, not something worth spending model judgment on, and scoping each
call to one chapter keeps input size and output-JSON reliability sane.

No explicit chain-of-thought prompting per Claude.md — reasoning_effort
is the tuning knob, not "think step by step" instructions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from groq_client import get_pool

STRUCTURE_MODEL = "openai/gpt-oss-120b"

_SYSTEM_PROMPT = """You are cleaning and structuring OCR'd text from one chapter of a Bangladeshi HSC Physics textbook.

The input is raw page text (Bangla, English, or mixed) that may contain OCR noise,
garbled math notation, and broken line breaks from page extraction.

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


def structure_chapter(chapter_text: str) -> list[StructuredChunk]:
    """Runs one chapter's concatenated page text through the Groq cleanup +
    structuring pass."""
    pool = get_pool()
    raw = pool.chat(
        model=STRUCTURE_MODEL,
        reasoning_effort="medium",
        json_mode=True,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": chapter_text},
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

"""Stage 2 — OCR for pages without a usable text layer.

Uses Google Cloud Vision's DOCUMENT_TEXT_DETECTION, which is tuned for
dense document pages (vs. the plain TEXT_DETECTION feature, meant for
sparse text in photos).

History: originally planned as self-hosted PaddleOCR, but PP-OCRv5
doesn't actually support Bengali. Tried EasyOCR next (does support
Bengali) but real testing showed ~90s/page on the target VM's CPU —
impractical at ~2,000 pages of pilot content. Vision API is faster,
benchmarks meaningfully more accurate, and costs ~$1.50 per 1,000
pages (first 1,000/month free) — a deliberate, founder-approved
departure from "fully self-hosted" for this one stage.

Auth: local dev uses `gcloud auth application-default login` (no key
file to manage). On the GCP VM, the instance's attached service
account should be granted Vision API access instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import vision

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

_LANGUAGE_HINTS = ["bn", "en"]


@dataclass
class OcrResult:
    text: str
    confidence: float  # page-level confidence, 0.0-1.0


def ocr_page(image_bytes: bytes) -> OcrResult:
    client = vision.ImageAnnotatorClient()
    image = vision.Image(content=image_bytes)
    image_context = vision.ImageContext(language_hints=_LANGUAGE_HINTS)

    response = client.document_text_detection(image=image, image_context=image_context)

    if response.error.message:
        raise RuntimeError(f"Vision API error: {response.error.message}")

    annotation = response.full_text_annotation
    if not annotation.pages:
        return OcrResult(text="", confidence=0.0)

    page = annotation.pages[0]
    return OcrResult(text=annotation.text, confidence=page.confidence)

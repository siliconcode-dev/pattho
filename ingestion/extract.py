"""Stage 1 — per-page text extraction.

Tries the PDF's embedded text layer first (fast, exact). Pages with too
little extractable text are assumed to be scanned images and flagged
for OCR (Stage 2) instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz

# Below this character count, a page is treated as "no usable text layer"
# (a bare page number or stray artifact can still produce a few chars).
MIN_NATIVE_TEXT_CHARS = 40

# Render scale for pages that need OCR — higher = better OCR accuracy,
# slower + more memory. 2.0 ≈ 144 DPI from a standard 72-DPI PDF page.
OCR_RENDER_SCALE = 2.0


@dataclass
class PageExtraction:
    page_number: int  # 1-indexed
    text: str | None  # native text, if usable
    needs_ocr: bool
    image_bytes: bytes | None = None  # populated only when needs_ocr


def extract_pages(pdf_path: Path) -> list[PageExtraction]:
    doc = fitz.open(pdf_path)
    results: list[PageExtraction] = []

    try:
        for index, page in enumerate(doc):
            text = page.get_text("text").strip()

            if len(text) >= MIN_NATIVE_TEXT_CHARS:
                results.append(
                    PageExtraction(page_number=index + 1, text=text, needs_ocr=False)
                )
                continue

            matrix = fitz.Matrix(OCR_RENDER_SCALE, OCR_RENDER_SCALE)
            pixmap = page.get_pixmap(matrix=matrix)
            results.append(
                PageExtraction(
                    page_number=index + 1,
                    text=text or None,
                    needs_ocr=True,
                    image_bytes=pixmap.tobytes("png"),
                )
            )
    finally:
        doc.close()

    return results

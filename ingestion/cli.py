"""Ingestion CLI — the founder-run entrypoint for Phase 1.

Run from inside the ingestion/ folder, with its venv active:

    cd ingestion
    python cli.py ingest --writer "Dr-Giasuddin-Ahmed" --book "Physics-1st-Paper" --paper 1st --path ../Data-Source/Dr-Giasuddin-Ahmed/1st-Paper/
    python cli.py ingest-board-questions --paper 1st --path ../Data-Source/Board-Questions/1st-Paper/

Boots nothing itself — assumes it's being run on a machine (dev box or
the GCP VM) with the venv already active and the repo root's
.env.local populated. See GCP_RUNBOOK.md for the production
start/stop flow on the VM.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from extract import extract_pages
from ocr import ocr_page
from qdrant_store import ChunkRecord, delete_chapter, ensure_collection, get_client, upsert_chunks
from embed import embed_chunks
from structure import structure_chapter

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
LOW_CONFIDENCE_THRESHOLD = 0.6

# Vision API calls are network-bound, not CPU-bound — OCR pages
# concurrently rather than one at a time. 10 is comfortably under
# Vision API's default per-project QPS limits for a solo pilot.
OCR_CONCURRENCY = 10

# Matches "02. ভেক্টর - দাগানো বই.pdf" -> chapter number "02", title "ভেক্টর".
# Falls back to the bare filename stem if a PDF doesn't follow this
# "<number>. <title> - <suffix>" convention.
_CHAPTER_FILENAME_PATTERN = re.compile(r"^(\d+)\.\s*(.+?)(?:\s*-\s*.+)?$")


def chapter_name_from_filename(pdf_path: Path) -> str:
    stem = pdf_path.stem
    match = _CHAPTER_FILENAME_PATTERN.match(stem)
    if not match:
        return stem
    number, title = match.groups()
    return f"{number}. {title}"


def _extract_pdf_text(pdf_path: Path) -> tuple[list[str], list[dict], list[int]]:
    """Returns (per-page text, per-page confidence log entries, page
    numbers) for one PDF. Pages needing OCR are sent to Vision API
    concurrently (network-bound, not CPU-bound) rather than one at a time.
    """
    pages = extract_pages(pdf_path)

    def resolve_page(page):
        if page.needs_ocr and page.image_bytes:
            ocr_result = ocr_page(page.image_bytes)
            return ocr_result.text, ocr_result.confidence
        return page.text or "", 1.0  # native text layer, no OCR uncertainty

    with ThreadPoolExecutor(max_workers=OCR_CONCURRENCY) as pool:
        resolved = list(pool.map(resolve_page, pages))

    page_texts = [text for text, _ in resolved]
    confidence_log = [
        {
            "file": pdf_path.name,
            "page": page.page_number,
            "confidence": confidence,
            "low_confidence": confidence < LOW_CONFIDENCE_THRESHOLD,
        }
        for page, (_, confidence) in zip(pages, resolved)
    ]
    page_numbers = [page.page_number for page in pages]

    return page_texts, confidence_log, page_numbers


def _write_confidence_log(writer: str, book: str, entries: list[dict]) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = LOGS_DIR / f"{writer}-{book}-{timestamp}.json"
    log_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")

    low_confidence_count = sum(1 for e in entries if e["low_confidence"])
    print(f"  Confidence log: {log_path} ({low_confidence_count}/{len(entries)} pages flagged low-confidence)")


def _ingest_pdfs(
    pdf_paths: list[Path],
    *,
    writer: str,
    book: str,
    paper: str,
    content_type: str,
    log_name: str,
) -> int:
    """Shared per-chapter pipeline for both `ingest` and
    `ingest-board-questions`. Each PDF is treated as one chapter — its
    name comes from the filename, not the LLM — and gets its own
    structuring call, so a book's ~10 chapters never get crammed into
    one oversized prompt.
    """
    client = get_client()
    ensure_collection(client)

    all_confidence_entries: list[dict] = []
    total_chunks = 0

    for pdf_path in pdf_paths:
        chapter = chapter_name_from_filename(pdf_path)
        print(f"[{chapter}] Extracting text from {pdf_path.name}...")
        page_texts, confidence_log, page_numbers = _extract_pdf_text(pdf_path)
        all_confidence_entries.extend(confidence_log)

        print(f"[{chapter}] Running structuring pass (Groq)...")
        chunks = structure_chapter(list(zip(page_numbers, page_texts)))
        print(f"[{chapter}] {len(chunks)} chunks produced")

        if not chunks:
            continue

        print(f"[{chapter}] Embedding chunks (BGE-M3)...")
        embeddings = embed_chunks([c.text for c in chunks])

        page_confidences = [e["confidence"] for e in confidence_log]
        chapter_confidence = (
            sum(page_confidences) / len(page_confidences) if page_confidences else None
        )

        records = [
            ChunkRecord(
                writer=writer,
                book=book,
                subject="Physics",
                paper=paper,
                chapter=chapter,
                topic=chunk.topic,
                subtopic=chunk.subtopic,
                content_type=content_type,
                chunk_type=chunk.chunk_type,
                source_pages=chunk.source_pages or page_numbers,
                ocr_confidence=chapter_confidence,
                text=chunk.text,
                chunk_index=i,
            )
            for i, chunk in enumerate(chunks)
        ]

        print(f"[{chapter}] Clearing any existing points for this chapter...")
        delete_chapter(client, writer, book, paper, chapter)

        print(f"[{chapter}] Upserting {len(records)} chunks to Qdrant...")
        upsert_chunks(client, records, embeddings)
        total_chunks += len(records)

    _write_confidence_log(log_name, book, all_confidence_entries)
    return total_chunks


def cmd_ingest(args: argparse.Namespace) -> None:
    pdf_dir = Path(args.path)
    pdf_paths = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_paths:
        print(f"No PDFs found in {pdf_dir}", file=sys.stderr)
        sys.exit(1)

    total = _ingest_pdfs(
        pdf_paths,
        writer=args.writer,
        book=args.book,
        paper=args.paper,
        content_type="textbook",
        log_name=args.writer,
    )
    print(f"Done. {total} chunks upserted for {args.writer} / {args.book} ({args.paper}) across {len(pdf_paths)} chapter(s).")


def cmd_ingest_board_questions(args: argparse.Namespace) -> None:
    pdf_dir = Path(args.path)
    pdf_paths = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_paths:
        print(f"No PDFs found in {pdf_dir}", file=sys.stderr)
        sys.exit(1)

    total = _ingest_pdfs(
        pdf_paths,
        writer="Board",
        book="HSC-Board-Questions",
        paper=args.paper,
        content_type="board-question",
        log_name="board-questions",
    )
    print(f"Done. {total} board-question chunks upserted ({args.paper}).")


def main() -> None:
    parser = argparse.ArgumentParser(prog="ingestion.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Ingest one writer's book")
    ingest.add_argument("--writer", required=True)
    ingest.add_argument("--book", required=True)
    ingest.add_argument("--paper", required=True, choices=["1st", "2nd"])
    ingest.add_argument("--path", required=True, help="Folder containing this book's PDFs")
    ingest.set_defaults(func=cmd_ingest)

    board = subparsers.add_parser("ingest-board-questions", help="Ingest past HSC board questions")
    board.add_argument("--paper", required=True, choices=["1st", "2nd"])
    board.add_argument("--path", required=True, help="Folder containing board-question PDFs")
    board.set_defaults(func=cmd_ingest_board_questions)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

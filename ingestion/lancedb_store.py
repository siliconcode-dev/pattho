"""Stage 5 — LanceDB table schema + storage.

Replaces qdrant_store.py (2026-09-08): Qdrant Cloud's 4GB free-tier
disk couldn't hold the full Physics corpus once ColBERT's per-token
multivectors were accounted for (~1.2MB/chunk), and Oracle Cloud's
Always Free ARM shape had no capacity in the founder's home region to
self-host a bigger Qdrant instead. LanceDB sidesteps the problem
entirely: it's an embedded library, not a server, so there's no
service capacity to run out of — it reads/writes its own file format
straight to object storage. Backing store here is Backblaze B2 (10GB
free forever, no credit card required to sign up, free egress),
accessed through its S3-compatible API — Cloudflare R2 was the first
choice but requires a card on file even to stay on its free tier.

Two vector columns per row (see the module docstring in embed.py for
why there's no third "sparse" column):
  - dense   (1024-dim, cosine)                -- primary semantic search
  - colbert (1024-dim multivector, MaxSim)     -- rerank only

No ANN/FTS index is built here — LanceDB does correct brute-force
search without one, which is more than fast enough at this corpus's
row count (low tens of thousands at most). Building `create_index`
(dense) and `create_fts_index` (text, BM25) is a one-time Phase 2
concern once retrieval is implemented and the corpus is stable, not
something ingestion needs to manage on every run.

Idempotency: `delete_chapter` clears every row already tagged with a
writer/book/paper/chapter before the fresh batch is inserted — same
reasoning as the old Qdrant version (the structuring LLM call isn't
guaranteed to produce the same chunk count/order on a re-run, so
positional indices alone can't be trusted). Since delete-then-add
already makes re-ingestion safe, there's no need for Qdrant-style
deterministic point IDs here — `_chunk_id` below exists only as a
stable human-readable reference for debugging, not a correctness
mechanism.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import lancedb
import pyarrow as pa
from dotenv import load_dotenv

from embed import ChunkEmbedding

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

TABLE_NAME = "pattho_physics"
DENSE_SIZE = 1024
COLBERT_SIZE = 1024

_SCHEMA = pa.schema(
    [
        pa.field("id", pa.string()),
        pa.field("writer", pa.string()),
        pa.field("book", pa.string()),
        pa.field("subject", pa.string()),
        pa.field("paper", pa.string()),
        pa.field("chapter", pa.string()),
        pa.field("topic", pa.string()),
        pa.field("subtopic", pa.string()),
        pa.field("content_type", pa.string()),
        pa.field("chunk_type", pa.string()),
        pa.field("source_pages", pa.list_(pa.int32())),
        pa.field("ocr_confidence", pa.float32()),
        pa.field("text", pa.string()),
        pa.field("dense", pa.list_(pa.float32(), DENSE_SIZE)),
        # Variable number of vectors per row (chunk length varies token
        # by token) — outer list has no fixed size, inner one does.
        pa.field("colbert", pa.list_(pa.list_(pa.float32(), COLBERT_SIZE))),
    ]
)


@dataclass
class ChunkRecord:
    writer: str
    book: str
    subject: str
    paper: str
    chapter: str
    topic: str
    subtopic: str | None
    content_type: str  # "textbook" | "board-question"
    chunk_type: str  # "narrative" | "worked_example"
    source_pages: list[int]
    ocr_confidence: float | None
    text: str
    chunk_index: int


def get_db() -> lancedb.DBConnection:
    # B2's S3-compatible API needs its actual region (e.g. "us-west-004"),
    # unlike R2 which accepts "auto" — Backblaze doesn't support "auto".
    return lancedb.connect(
        os.environ["LANCEDB_URI"],  # e.g. s3://pattho-vectors/lancedb
        storage_options={
            "endpoint": os.environ["B2_ENDPOINT"],
            "region": os.environ["B2_REGION"],
            "aws_access_key_id": os.environ["B2_KEY_ID"],
            "aws_secret_access_key": os.environ["B2_APPLICATION_KEY"],
        },
    )


def ensure_table(db: lancedb.DBConnection) -> lancedb.table.Table:
    if TABLE_NAME in db.table_names():
        return db.open_table(TABLE_NAME)
    return db.create_table(TABLE_NAME, schema=_SCHEMA)


def _escape(value: str) -> str:
    return value.replace("'", "''")


def delete_chapter(table: lancedb.table.Table, writer: str, book: str, paper: str, chapter: str) -> None:
    """Removes every existing row for this exact writer/book/paper/chapter
    before a fresh ingestion run inserts its replacement chunks — see the
    idempotency note in the module docstring for why this is needed.
    """
    table.delete(
        f"writer = '{_escape(writer)}' AND book = '{_escape(book)}' "
        f"AND paper = '{_escape(paper)}' AND chapter = '{_escape(chapter)}'"
    )


def _chunk_id(record: ChunkRecord) -> str:
    key = f"{record.writer}|{record.book}|{record.paper}|{record.chapter}|{record.chunk_index}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def upsert_chunks(
    table: lancedb.table.Table,
    records: list[ChunkRecord],
    embeddings: list[ChunkEmbedding],
) -> None:
    rows = [
        {
            "id": _chunk_id(record),
            "writer": record.writer,
            "book": record.book,
            "subject": record.subject,
            "paper": record.paper,
            "chapter": record.chapter,
            "topic": record.topic,
            "subtopic": record.subtopic,
            "content_type": record.content_type,
            "chunk_type": record.chunk_type,
            "source_pages": record.source_pages,
            "ocr_confidence": record.ocr_confidence,
            "text": record.text,
            "dense": embedding.dense,
            "colbert": embedding.colbert,
        }
        for record, embedding in zip(records, embeddings)
    ]
    table.add(rows)

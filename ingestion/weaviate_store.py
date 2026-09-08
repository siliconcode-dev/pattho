"""Stage 5 — Weaviate Cloud collection schema + idempotent upsert.

Third vector-store choice for Phase 1 (2026-09-08): Qdrant Cloud's 4GB
free-tier disk couldn't hold the full Physics corpus once ColBERT's
per-token multivectors were counted (~1.2MB/chunk). LanceDB (embedded,
writing to object storage) looked like a clean fix, but Cloudflare R2
requires a card on file and Backblaze B2's S3-compatible API doesn't
support the conditional-PUT writes LanceDB's commit protocol requires
(a real, currently-unresolved incompatibility — see
https://github.com/lance-format/lance/issues/3638). Google Cloud
Storage would work technically but bills the founder's live GCP card
on any overage, which the corpus's actual size makes likely past its
5GB free tier.

Weaviate Cloud's free tier (changed Oct 2025 to a genuinely permanent
free plan, not the old 14-day sandbox) sidesteps the storage-backend
problem entirely: it's a hosted cluster like Qdrant was, no credit
card, 10GB disk. It also has native BM25 full-text search built in, so
there's no need to bring our own sparse vectors either (see embed.py's
docstring). ColBERT-style multivector reranking was tried too, but the
free sandbox forces the `hfresh` vector index (its only HNSW
alternative is banned there) and `hfresh` doesn't implement multivector
support server-side yet — confirmed with a live insert error, not just
docs — so that part of the original design was dropped for v1.

One vector per object:
  - dense (1024-dim, self-provided, cosine, hfresh index)

Idempotency: `delete_chapter` clears every object already tagged with
a writer/book/paper/chapter before the fresh batch is inserted — the
structuring LLM call isn't guaranteed to produce the same chunk
count/order on a re-run, so a delete-then-insert is what makes
re-ingestion safe, not the object's UUID alone (though the UUID is
still deterministic, for a stable human-readable reference).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import weaviate
from dotenv import load_dotenv
from weaviate.auth import AuthApiKey
from weaviate.classes.config import Configure, DataType, Property
from weaviate.classes.query import Filter
from weaviate.util import generate_uuid5

from embed import ChunkEmbedding

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

COLLECTION_NAME = "PatthoPhysics"


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


def get_client() -> weaviate.WeaviateClient:
    return weaviate.connect_to_weaviate_cloud(
        cluster_url=os.environ["WEAVIATE_URL"],
        auth_credentials=AuthApiKey(os.environ["WEAVIATE_API_KEY"]),
    )


def ensure_collection(client: weaviate.WeaviateClient) -> None:
    if client.collections.exists(COLLECTION_NAME):
        return

    client.collections.create(
        COLLECTION_NAME,
        # Weaviate Cloud's free-tier sandbox only allows the "hfresh" vector
        # index (memory-efficient — keeps compressed postings on disk
        # instead of the full index in RAM, which matters on the 1GB
        # memory allowance), not the default HNSW.
        vector_config=[
            Configure.Vectors.self_provided(name="dense", vector_index_config=Configure.VectorIndex.hfresh()),
        ],
        properties=[
            Property(name="writer", data_type=DataType.TEXT),
            Property(name="book", data_type=DataType.TEXT),
            Property(name="subject", data_type=DataType.TEXT),
            Property(name="paper", data_type=DataType.TEXT),
            Property(name="chapter", data_type=DataType.TEXT),
            Property(name="topic", data_type=DataType.TEXT),
            Property(name="subtopic", data_type=DataType.TEXT),
            Property(name="content_type", data_type=DataType.TEXT),
            Property(name="chunk_type", data_type=DataType.TEXT),
            Property(name="source_pages", data_type=DataType.INT_ARRAY),
            Property(name="ocr_confidence", data_type=DataType.NUMBER),
            Property(name="text", data_type=DataType.TEXT),
        ],
    )


def chapter_exists(client: weaviate.WeaviateClient, writer: str, book: str, paper: str, chapter: str) -> bool:
    """Used to make bulk ingestion resumable at chapter granularity: Groq's
    daily quota can run out mid-batch (a real, observed failure mode — see
    GCP_RUNBOOK.md), and re-running from chapter 1 every retry would waste
    scarce tokens re-structuring chapters that already succeeded.
    """
    collection = client.collections.use(COLLECTION_NAME)
    result = collection.aggregate.over_all(
        filters=(
            Filter.by_property("writer").equal(writer)
            & Filter.by_property("book").equal(book)
            & Filter.by_property("paper").equal(paper)
            & Filter.by_property("chapter").equal(chapter)
        ),
        total_count=True,
    )
    return result.total_count > 0


def delete_chapter(client: weaviate.WeaviateClient, writer: str, book: str, paper: str, chapter: str) -> None:
    """Removes every existing object for this exact writer/book/paper/chapter
    before a fresh ingestion run inserts its replacement chunks — see the
    idempotency note in the module docstring for why this is needed.
    """
    collection = client.collections.use(COLLECTION_NAME)
    collection.data.delete_many(
        where=(
            Filter.by_property("writer").equal(writer)
            & Filter.by_property("book").equal(book)
            & Filter.by_property("paper").equal(paper)
            & Filter.by_property("chapter").equal(chapter)
        )
    )


def _object_uuid(record: ChunkRecord) -> str:
    key = f"{record.writer}|{record.book}|{record.paper}|{record.chapter}|{record.chunk_index}"
    return generate_uuid5(key)


def upsert_chunks(
    client: weaviate.WeaviateClient,
    records: list[ChunkRecord],
    embeddings: list[ChunkEmbedding],
) -> None:
    collection = client.collections.use(COLLECTION_NAME)
    objects = [
        weaviate.classes.data.DataObject(
            uuid=_object_uuid(record),
            properties={
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
            },
            vector={"dense": embedding.dense},
        )
        for record, embedding in zip(records, embeddings)
    ]
    collection.data.insert_many(objects)

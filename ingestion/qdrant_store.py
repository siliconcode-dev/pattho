"""Stage 5 — Qdrant collection schema + idempotent upsert.

Three named vectors per point:
  - dense   (1024-dim, COSINE, HNSW on)  -- primary semantic search
  - sparse  (BGE-M3 lexical weights)     -- keyword-style matching
  - colbert (1024-dim multivector, COSINE, MAX_SIM, HNSW off) -- rerank only

Idempotency: point IDs are a deterministic hash of
writer+book+paper+chapter+chunk-index, but that alone isn't a full
guarantee — the structuring LLM call isn't guaranteed to produce the
exact same number/order of chunks on a re-run, so positional chunk
indices could map to different content between runs, or a re-run
with fewer chunks could leave old extras orphaned. `delete_chapter`
makes re-ingestion actually safe: it clears every point already
tagged with that writer/book/paper/chapter before the fresh batch is
inserted, so a chapter's old points never linger.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient, models

from embed import ChunkEmbedding

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

COLLECTION_NAME = "pattho_physics"
DENSE_SIZE = 1024
# BGE-M3's colbert_vecs are 1024-dim (matches its dense hidden size),
# not the 128-dim used by classic ColBERT — confirmed from a real
# Qdrant dimension-mismatch error, not just assumed from general
# ColBERT knowledge.
COLBERT_SIZE = 1024


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


def get_client() -> QdrantClient:
    # prefer_grpc: ColBERT's per-token multivectors make points large, and
    # Qdrant's REST API JSON-encodes every float as decimal text (~3-4x
    # bloat vs binary) - gRPC's protobuf encoding avoids that entirely.
    #
    # timeout: qdrant-client defaults to a hardcoded 5s, which isn't
    # enough for a batch of ColBERT-heavy points to finish indexing
    # server-side, especially given the VM-to-cluster region gap
    # (asia-southeast1 -> australia-southeast1). 60s covers normal
    # batches; _upsert_batch still splits+retries on a timeout anyway
    # for the rare oversized one.
    return QdrantClient(
        url=os.environ["QDRANT_URL"],
        api_key=os.environ["QDRANT_API_KEY"],
        prefer_grpc=True,
        timeout=60,
    )


def ensure_collection(client: QdrantClient) -> None:
    if client.collection_exists(COLLECTION_NAME):
        return

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            "dense": models.VectorParams(
                size=DENSE_SIZE,
                distance=models.Distance.COSINE,
            ),
            "colbert": models.VectorParams(
                size=COLBERT_SIZE,
                distance=models.Distance.COSINE,
                multivector_config=models.MultiVectorConfig(
                    comparator=models.MultiVectorComparator.MAX_SIM
                ),
                hnsw_config=models.HnswConfigDiff(m=0),  # rerank-only, no HNSW index
            ),
        },
        sparse_vectors_config={
            "sparse": models.SparseVectorParams(),
        },
    )


def delete_chapter(client: QdrantClient, writer: str, book: str, paper: str, chapter: str) -> None:
    """Removes every existing point for this exact writer/book/paper/chapter
    before a fresh ingestion run inserts its replacement chunks — see the
    idempotency note in the module docstring for why this is needed on top
    of the deterministic point IDs.
    """
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(key="writer", match=models.MatchValue(value=writer)),
                    models.FieldCondition(key="book", match=models.MatchValue(value=book)),
                    models.FieldCondition(key="paper", match=models.MatchValue(value=paper)),
                    models.FieldCondition(key="chapter", match=models.MatchValue(value=chapter)),
                ]
            )
        ),
    )


def _point_id(record: ChunkRecord) -> str:
    key = f"{record.writer}|{record.book}|{record.paper}|{record.chapter}|{record.chunk_index}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return str(uuid.UUID(digest[:32]))


def upsert_chunks(
    client: QdrantClient,
    records: list[ChunkRecord],
    embeddings: list[ChunkEmbedding],
) -> None:
    points = []
    for record, embedding in zip(records, embeddings):
        points.append(
            models.PointStruct(
                id=_point_id(record),
                vector={
                    "dense": embedding.dense,
                    "sparse": models.SparseVector(
                        indices=list(embedding.sparse.keys()),
                        values=list(embedding.sparse.values()),
                    ),
                    "colbert": embedding.colbert,
                },
                payload={
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
            )
        )

    _upsert_batch(client, points)


def _should_split_and_retry(error: Exception) -> bool:
    # REST path (qdrant_client.http.exceptions.UnexpectedResponse)
    status = getattr(error, "status_code", None)
    content = getattr(error, "content", None)
    if status == 400 and content and b"larger than allowed" in content:
        return True

    # gRPC path (grpc.RpcError) — no status_code/content attributes;
    # surfaces via .code()/.details() instead. RESOURCE_EXHAUSTED is
    # gRPC's standard code for oversized messages either direction.
    code_fn = getattr(error, "code", None)
    details_fn = getattr(error, "details", None)
    if callable(code_fn) and callable(details_fn):
        code = code_fn()
        details = (details_fn() or "").lower()
        if code is not None and code.name in ("RESOURCE_EXHAUSTED", "DEADLINE_EXCEEDED"):
            return True
        if "larger than allowed" in details or "message length" in details:
            return True

    return False


def _upsert_batch(client: QdrantClient, points: list) -> None:
    """Upserts points, halving the batch and retrying on a too-large
    payload or a timeout — ColBERT multivectors mean point size (and
    server-side indexing time) varies a lot with chunk text length, so
    no fixed batch size is safe for every book. Mirrors the same
    adaptive pattern used for Groq's token limit in structure.py.
    """
    if not points:
        return

    try:
        client.upsert(collection_name=COLLECTION_NAME, points=points)
    except Exception as error:  # noqa: BLE001 — only split on the specific too-large/timeout case
        if not _should_split_and_retry(error) or len(points) == 1:
            raise

        midpoint = len(points) // 2
        print(
            f"    (upsert batch of {len(points)} points too large/slow, splitting into "
            f"{midpoint} + {len(points) - midpoint})"
        )
        _upsert_batch(client, points[:midpoint])
        _upsert_batch(client, points[midpoint:])

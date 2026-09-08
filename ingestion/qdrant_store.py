"""Stage 5 — Qdrant collection schema + idempotent upsert.

Three named vectors per point:
  - dense   (1024-dim, COSINE, HNSW on)  -- primary semantic search
  - sparse  (BGE-M3 lexical weights)     -- keyword-style matching
  - colbert (128-dim multivector, COSINE, MAX_SIM, HNSW off) -- rerank only

Point IDs are a deterministic hash of writer+book+paper+chapter+chunk-index,
so re-running ingestion for one book overwrites its own points cleanly
without touching any other writer/book (this is what makes incremental,
per-writer/per-book ingestion safe).
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
COLBERT_SIZE = 128


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
    return QdrantClient(
        url=os.environ["QDRANT_URL"],
        api_key=os.environ["QDRANT_API_KEY"],
        prefer_grpc=True,
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


def _is_payload_too_large(error: Exception) -> bool:
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
        if code is not None and code.name == "RESOURCE_EXHAUSTED":
            return True
        if "larger than allowed" in details or "message length" in details:
            return True

    return False


def _upsert_batch(client: QdrantClient, points: list) -> None:
    """Upserts points, halving the batch and retrying if it's still too
    large even over gRPC — ColBERT multivectors mean point size varies a
    lot with chunk text length, so no fixed batch size is safe for every
    book. Mirrors the same adaptive pattern used for Groq's token limit
    in structure.py.
    """
    if not points:
        return

    try:
        client.upsert(collection_name=COLLECTION_NAME, points=points)
    except Exception as error:  # noqa: BLE001 — only split on the specific too-large case
        if not _is_payload_too_large(error) or len(points) == 1:
            raise

        midpoint = len(points) // 2
        print(
            f"    (upsert batch of {len(points)} points too large, splitting into "
            f"{midpoint} + {len(points) - midpoint})"
        )
        _upsert_batch(client, points[:midpoint])
        _upsert_batch(client, points[midpoint:])

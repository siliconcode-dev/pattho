"""Stage 4 — embedding via BGE-M3 (dense + ColBERT multi-vector).

One model, one encode() call produces both representations the
LanceDB table schema (lancedb_store.py) expects. BGE-M3 can also emit
a sparse lexical-weights vector, but LanceDB has no first-class sparse
vector column (unlike Qdrant's SparseVectorParams) — its keyword-match
role is instead covered by LanceDB's own native BM25 full-text index
over the stored `text` column, built in Phase 2 once retrieval is
implemented. So `return_sparse` is left off here: it would just be
computed and discarded.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from FlagEmbedding import BGEM3FlagModel

MODEL_NAME = "BAAI/bge-m3"


@dataclass
class ChunkEmbedding:
    dense: list[float]
    colbert: list[list[float]]  # one 1024-dim vector per token


@lru_cache(maxsize=1)
def _get_model() -> BGEM3FlagModel:
    # CPU inference — the GCP VM has no GPU. use_fp16=False since fp16
    # only helps on GPU; on CPU it can silently degrade quality.
    return BGEM3FlagModel(MODEL_NAME, use_fp16=False, device="cpu")


def embed_chunks(texts: list[str]) -> list[ChunkEmbedding]:
    model = _get_model()
    output = model.encode(
        texts,
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=True,
    )

    results = []
    for i in range(len(texts)):
        results.append(
            ChunkEmbedding(
                dense=output["dense_vecs"][i].tolist(),
                colbert=output["colbert_vecs"][i].tolist(),
            )
        )
    return results

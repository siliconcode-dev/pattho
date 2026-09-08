"""Stage 4 — embedding via BGE-M3 (dense + sparse + ColBERT multi-vector).

One model, one encode() call produces all three representations the
Qdrant collection schema (qdrant_store.py) expects.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from FlagEmbedding import BGEM3FlagModel

MODEL_NAME = "BAAI/bge-m3"


@dataclass
class ChunkEmbedding:
    dense: list[float]
    sparse: dict[int, float]  # token-id -> weight
    colbert: list[list[float]]  # one 128-dim vector per token


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
        return_sparse=True,
        return_colbert_vecs=True,
    )

    results = []
    for i in range(len(texts)):
        sparse_weights = output["lexical_weights"][i]
        results.append(
            ChunkEmbedding(
                dense=output["dense_vecs"][i].tolist(),
                sparse={int(token_id): float(w) for token_id, w in sparse_weights.items()},
                colbert=output["colbert_vecs"][i].tolist(),
            )
        )
    return results

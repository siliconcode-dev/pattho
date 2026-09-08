"""Stage 4 — embedding via BGE-M3 (dense only).

BGE-M3 can also emit sparse lexical-weights and ColBERT-style
per-token multivectors, but neither made it into the final vector
store design (2026-09-08):

- Sparse: Weaviate Cloud has no first-class sparse vector column
  (unlike Qdrant's SparseVectorParams). Its keyword-match role is
  instead covered by Weaviate's own native BM25 full-text index over
  the stored `text` property, used in Phase 2's hybrid search.
- ColBERT multivector: Weaviate's free-tier sandbox forces the
  memory-efficient `hfresh` vector index (its only allowed HNSW
  alternative is banned there), but `hfresh` doesn't implement
  multivector support server-side yet — confirmed with a live error
  (`*hfresh.HFresh is not common.VectorIndexMulti`), not just docs.
  Late-interaction reranking is dropped for v1 as a result; dense +
  BM25 hybrid is still a solid retrieval baseline. Revisit if the
  founder ever pays for a Weaviate tier or self-hosts open-source
  Weaviate, where HNSW (and multivector) would be available.

So `return_sparse` and `return_colbert_vecs` are both left off — they
would just be computed and discarded.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from FlagEmbedding import BGEM3FlagModel

MODEL_NAME = "BAAI/bge-m3"


@dataclass
class ChunkEmbedding:
    dense: list[float]


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
        return_colbert_vecs=False,
    )
    return [ChunkEmbedding(dense=vec.tolist()) for vec in output["dense_vecs"]]

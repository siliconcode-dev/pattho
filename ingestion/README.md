# Ingestion pipeline

Turns Physics PDFs (multiple writers, both papers) into metadata-tagged
vectors in Qdrant. See `../Build_plan.md` Phase 1 and the plan history for
full context.

## Local setup

```
cd ingestion
python -m venv .venv
.venv/Scripts/activate   # Windows
pip install -r requirements.txt
```

Reads Groq/Qdrant credentials from the repo root's `.env.local` (same file
Phase 0's Next.js app uses) — nothing extra to configure.

## Running

```
python cli.py ingest --writer "<Writer>" --book "<Book>" --paper 1st --path ../Data-Source/<Writer>/1st-Paper/
python cli.py ingest-board-questions --paper 1st --path ../Data-Source/Board-Questions/1st-Paper/
```

Re-running `ingest` for the same writer/book/paper/chapter is safe — each
chapter's existing points are deleted before its fresh chunks are inserted
(point IDs alone aren't a strong enough guarantee, since the structuring
LLM call isn't guaranteed to produce the same chunk count/order every run).

Each run writes a per-page OCR confidence log to `../logs/`.

## Groq daily quota — check before a big batch

```
python check_quota.py         # cheap: confirms keys still authenticate
python check_quota.py --big   # expensive (~20k tokens/key): real daily-headroom check
```

The 6 `GROQ_API_KEY*` keys are **not one shared pool** — verified
2026-09-08: 4 belong to 4 distinct Groq orgs, the other 2 share a 5th, so
there are really 5 independent ~200k-token/day budgets. A single chapter's
structuring pass (with the adaptive page-batch splitting in `structure.py`)
costs roughly 20-40k tokens in the clean case — so all 5 pools combined
can realistically cover maybe 25-50 chapters/day, but repeated debugging
runs burn through that fast (a day of heavy iteration exhausted nearly the
full ~1M combined daily budget). Run `check_quota.py --big` before kicking
off a large batch if you're not sure there's headroom left.

## Pipeline stages

| Stage | File | What it does |
|---|---|---|
| 1. Extract | `extract.py` | PyMuPDF text-layer detection; rasterizes pages that need OCR |
| 2. OCR | `ocr.py` | Google Cloud Vision (DOCUMENT_TEXT_DETECTION) — see `GCP_RUNBOOK.md` for one-time setup |
| 3. Structure | `structure.py` | Groq cleanup + topic/subtopic/worked-example segmentation (chapter comes from the source filename) |
| 4. Embed | `embed.py` | BGE-M3 dense + sparse + ColBERT |
| 5. Store | `qdrant_store.py` | Collection schema + idempotent upsert |

OCR was originally planned as self-hosted (PaddleOCR, then EasyOCR), but
real testing showed EasyOCR ran ~90s/page on CPU — impractical at pilot
scale (~2,000 pages). Switched to Google Cloud Vision API: faster, more
accurate, and ~$1.50/1,000 pages (first 1,000/month free). See
`GCP_RUNBOOK.md` for the one-time API-enable + auth setup.

`groq_client.py` is a Python port of `../src/lib/groq/client.ts`'s key
rotation pool — keep retry/rotation behavior in sync between the two if
either changes.

## Production runs

Ingestion should actually run on the GCP VM (`ocr-patho-ai`), not a laptop,
per the boot-on-demand compute pattern. See `GCP_RUNBOOK.md`.

# Ingestion pipeline

Turns Physics PDFs (multiple writers, both papers) into metadata-tagged
vectors in Weaviate Cloud. See `../Build_plan.md` Phase 1 and the plan
history for full context.

## Weaviate Cloud setup (one-time)

Third vector-store choice for this phase (2026-09-08) — Qdrant Cloud's
4GB free-tier disk ran out once ColBERT's per-token multivectors were
counted (~1.2MB/chunk), and a LanceDB (embedded, object-storage-backed)
alternative hit real dead ends: Cloudflare R2 needs a card on file,
Backblaze B2's S3-compatible API doesn't support the conditional-PUT
writes LanceDB's commit protocol requires, and Google Cloud Storage
would bill the founder's live GCP card on any overage. Weaviate Cloud's
free tier (genuinely permanent since Oct 2025, not the old 14-day
sandbox) is a hosted cluster like Qdrant was — no credit card, 10GB
disk, 100k objects — with native hybrid (dense+BM25) search and
ColBERT-style multivector MaxSim built in, so there's no storage-backend
compatibility risk at all. See `weaviate_store.py`'s docstring.

1. Sign up at console.weaviate.cloud (no card needed).
2. Create a cluster (Database → Create a cluster → free Sandbox tier).
3. Once it's running, copy the **REST endpoint URL** and the **Admin
   API key** from the cluster's details page.
4. Fill in `WEAVIATE_URL` and `WEAVIATE_API_KEY` in the repo root's
   `.env.local`.

## Local setup

```
cd ingestion
python -m venv .venv
.venv/Scripts/activate   # Windows
pip install -r requirements.txt
```

Reads Groq/Weaviate credentials from the repo root's `.env.local` (same
file Phase 0's Next.js app uses) — nothing extra to configure, once the
Weaviate setup above is done.

## Running

```
python cli.py ingest --writer "<Writer>" --book "<Book>" --paper 1st --path ../Data-Source/<Writer>/1st-Paper/
python cli.py ingest-board-questions --paper 1st --path ../Data-Source/Board-Questions/1st-Paper/
```

Re-running `ingest` for the same writer/book/paper/chapter is safe — each
chapter's existing objects are deleted before its fresh chunks are
inserted (the structuring LLM call isn't guaranteed to produce the same
chunk count/order every run, so a delete-then-insert is what makes this
safe, not just a stable object UUID).

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
| 4. Embed | `embed.py` | BGE-M3 dense + ColBERT (no sparse — see file docstring) |
| 5. Store | `weaviate_store.py` | Collection schema + idempotent upsert, on Weaviate Cloud |

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

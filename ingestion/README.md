# Ingestion pipeline

Turns Physics PDFs (multiple writers, both papers) into metadata-tagged
vectors in LanceDB (on Backblaze B2). See `../Build_plan.md` Phase 1 and
the plan history for full context.

## B2 + LanceDB setup (one-time)

LanceDB is an embedded library, not a hosted service — there's no account
to sign up for beyond the storage backend it writes to. We use Backblaze
B2 (10GB free forever, no credit card required, free egress), replacing
Qdrant Cloud 2026-09-08 after its 4GB free-tier disk proved too small for
ColBERT's per-token multivectors (~1.2MB/chunk); Oracle's Always Free ARM
tier had no self-host capacity in-region, and Cloudflare R2 (the first
alternative considered) requires a card on file even to stay free. See
`lancedb_store.py`'s docstring.

1. Sign up at backblaze.com/sign-up/cloud-storage (no card needed).
2. Create a bucket (e.g. `pattho-vectors`) — note the region shown
   (e.g. `us-west-004`).
3. App Keys page → Add a New Application Key, scoped to that bucket,
   Read and Write. Copy the `keyID` and `applicationKey` — the key is
   only shown once.
4. Endpoint is `https://s3.<region>.backblazeb2.com`.
5. Fill in `LANCEDB_URI`, `B2_ENDPOINT`, `B2_REGION`, `B2_KEY_ID`,
   `B2_APPLICATION_KEY` in the repo root's `.env.local`.

## Local setup

```
cd ingestion
python -m venv .venv
.venv/Scripts/activate   # Windows
pip install -r requirements.txt
```

Reads Groq/LanceDB(B2) credentials from the repo root's `.env.local` (same
file Phase 0's Next.js app uses) — nothing extra to configure, once the B2
setup above is done.

## Running

```
python cli.py ingest --writer "<Writer>" --book "<Book>" --paper 1st --path ../Data-Source/<Writer>/1st-Paper/
python cli.py ingest-board-questions --paper 1st --path ../Data-Source/Board-Questions/1st-Paper/
```

Re-running `ingest` for the same writer/book/paper/chapter is safe — each
chapter's existing rows are deleted before its fresh chunks are inserted
(the structuring LLM call isn't guaranteed to produce the same chunk
count/order every run, so a delete-then-add is what makes this safe, not
just a stable row ID).

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
| 5. Store | `lancedb_store.py` | Table schema + idempotent write, on Backblaze B2 |

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

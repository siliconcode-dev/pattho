# GCP runbook — ingestion runs

**Status: the dedicated `ocr-patho-ai` VM is no longer required.** OCR moved
from self-hosted EasyOCR (too slow on CPU — ~90s/page) to Google Cloud
Vision API, which does the heavy lifting server-side. The founder
suspended/deleted the VM accordingly. The pipeline now runs fine directly
from a laptop for pilot-scale content (~2,000 pages).

If BGE-M3 embedding (Stage 4) ever turns out too slow locally at larger
content volumes, a VM can be recreated cheaply from this spec — nothing
unique lives on it, all real data is in `Data-Source/` and Weaviate Cloud:
`e2-custom-4-12288` (4 vCPU / 12GB), `asia-southeast1`, 50-65GB balanced
disk, no snapshot schedule, Ops Agent off. See the Phase 0 plan history for
the full walkthrough if you need to redo it.

## Vision API setup (replaces the old VM-based OCR setup)

1. Enable the API for the project:
   ```
   gcloud services enable vision.googleapis.com --project=ocr-pattho
   ```
   (or Console → APIs & Services → Enable APIs → search "Cloud Vision API")

2. Authenticate locally (one-time):
   ```
   gcloud auth application-default login
   ```
   This lets `ingestion/ocr.py`'s `google-cloud-vision` client pick up
   credentials automatically — no key file to manage or accidentally commit.

3. Confirm billing is enabled on the project (Vision API requires it, even
   though the first 1,000 pages/month are free).

## Running ingestion

Same as `ingestion/README.md` — just run it locally now:

```
cd ingestion
source .venv/Scripts/activate   # Windows
python cli.py ingest --writer "<Writer>" --book "<Book>" --paper 1st --path ../Data-Source/<Writer>/1st-Paper/
```

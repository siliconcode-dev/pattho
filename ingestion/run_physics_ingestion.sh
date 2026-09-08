#!/usr/bin/env bash
# Sequential bulk ingestion for full Physics 1st + 2nd Paper (both writers).
# Each command only starts once the previous one exits successfully (set -e)
# so a failure partway through stops the chain instead of silently skipping
# ahead into a book whose earlier chapters never made it in.
#
# --skip-existing on every command makes a retry (see
# run_physics_ingestion_with_retry.sh) resume at chapter granularity
# instead of redoing already-successful chapters and wasting scarce Groq
# quota re-structuring them.
set -e
cd "$(dirname "$0")"
source .venv/bin/activate

echo "=== $(date -u +%FT%TZ) Starting Ishak Sir - Physics 1st Paper ==="
python3 cli.py ingest --writer "Ishak Sir" --book "Physics-1st-Paper" --paper 1st \
  --path "../Data-Source/Physics 1st Paper/Ishak Sir/" --skip-existing

echo "=== $(date -u +%FT%TZ) Starting Topon Sir - Physics 1st Paper ==="
python3 cli.py ingest --writer "Topon Sir" --book "Physics-1st-Paper" --paper 1st \
  --path "../Data-Source/Physics 1st Paper/Topon Sir/" --skip-existing

echo "=== $(date -u +%FT%TZ) Physics 1st Paper complete. Starting Ishak Sir - Physics 2nd Paper ==="
python3 cli.py ingest --writer "Ishak Sir" --book "Physics-2nd-Paper" --paper 2nd \
  --path "../Data-Source/Physics 2nd Paper/Ishak Sir/" --skip-existing

echo "=== $(date -u +%FT%TZ) Starting Topon Sir - Physics 2nd Paper ==="
python3 cli.py ingest --writer "Topon Sir" --book "Physics-2nd-Paper" --paper 2nd \
  --path "../Data-Source/Physics 2nd Paper/Topon Sir/" --skip-existing

echo "=== $(date -u +%FT%TZ) All four books complete. ==="

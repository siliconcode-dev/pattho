#!/usr/bin/env bash
# Wraps run_physics_ingestion.sh with automatic retry on Groq quota
# exhaustion. groq_client.py deliberately raises instead of sleeping
# itself when every key is rate-limited (a multi-hour wait belongs in
# the caller's hands, not silently inside the retry library — see its
# docstring) — this script is that caller.
#
# Safe to retry blindly: run_physics_ingestion.sh passes --skip-existing
# on every command, so a retry only spends time/tokens re-attempting the
# chapter that failed, not the whole batch from scratch.
cd "$(dirname "$0")"
RETRY_SECONDS=1200  # 20 min between attempts
ATTEMPT=1

while true; do
  echo "=== $(date -u +%FT%TZ) Attempt $ATTEMPT ==="
  if ./run_physics_ingestion.sh; then
    echo "=== $(date -u +%FT%TZ) All books completed successfully after $ATTEMPT attempt(s). ==="
    exit 0
  fi
  echo "=== $(date -u +%FT%TZ) Attempt $ATTEMPT failed — retrying in ${RETRY_SECONDS}s ==="
  ATTEMPT=$((ATTEMPT + 1))
  sleep "$RETRY_SECONDS"
done

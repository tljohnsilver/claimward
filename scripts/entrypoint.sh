#!/usr/bin/env bash
set -euo pipefail
PORT="${PORT:-8080}"
mkdir -p data/evidence data/sample_denials data/clinical_criteria
echo "[ClaimWard] Starting FastAPI on 0.0.0.0:${PORT}"
exec uvicorn src.dashboard:app --host 0.0.0.0 --port "${PORT}"

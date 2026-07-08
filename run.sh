#!/usr/bin/env bash
# SENTINEL — one-command local startup (Linux/macOS, no Docker needed)
# Usage:  ./run.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "SENTINEL bootstrap"

# ── backend ──────────────────────────────────────────────────────────────
if [ ! -d "$ROOT/backend/.venv" ]; then
  echo "[1/4] creating Python venv..."
  python3 -m venv "$ROOT/backend/.venv"
else
  echo "[1/4] venv exists"
fi

echo "[2/4] installing backend deps (ML stack is ~2.5 GB on first run)..."
"$ROOT/backend/.venv/bin/pip" install -q -r "$ROOT/backend/requirements.txt"
"$ROOT/backend/.venv/bin/pip" install -q -r "$ROOT/backend/requirements-ml.txt"

if [ ! -d "$ROOT/backend/app/ml/models/threat-classifier" ]; then
  echo "NOTE: no fine-tuned threat classifier yet. Train it once with:"
  echo "      cd backend && .venv/bin/python -m app.ml.train"
  echo "      (until then, full mode uses the slower zero-shot model)"
fi

echo "[3/4] starting backend on http://localhost:8000 ..."
(cd "$ROOT/backend" && .venv/bin/python -m uvicorn app.main:app --port 8000) &
BACK_PID=$!

# ── frontend ─────────────────────────────────────────────────────────────
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "[4/4] installing frontend deps..."
  (cd "$ROOT/frontend" && npm install)
else
  echo "[4/4] node_modules exists"
fi

echo "starting frontend on http://localhost:5173 ..."
(cd "$ROOT/frontend" && npm run dev) &
FRONT_PID=$!

trap 'kill $BACK_PID $FRONT_PID 2>/dev/null' EXIT
echo ""
echo "SENTINEL is live -> http://localhost:5173  (API docs: http://localhost:8000/docs)"
wait

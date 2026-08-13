#!/usr/bin/env bash
# SENTINEL - one-command local startup (Linux/macOS)
#
#   ./run.sh                 install what is missing, start both, print the URLs
#   ./run.sh --skip-install  straight to starting (fastest, once set up)
#
# Both services run as children of THIS shell, with their output interleaved
# and labelled [api] / [web]. Ctrl+C stops both. The Windows twin is run.ps1
# and behaves the same way.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/backend/.venv"
PY="$VENV/bin/python"
STAMP="$VENV/.deps-stamp"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
SKIP_INSTALL=0
[ "${1:-}" = "--skip-install" ] && SKIP_INSTALL=1

step() { printf '\033[36m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33m    %s\033[0m\n' "$1"; }

cleanup() {
    printf '\n'
    step "stopping SENTINEL"
    # The whole process group: uvicorn's reloader and vite's esbuild are
    # children, and killing only the parents leaves the ports held.
    kill 0 2>/dev/null || true
}
trap cleanup EXIT INT TERM

printf '\n  \033[32mSENTINEL\033[0m  -  Gujarat Police social-media intelligence\n\n'

command -v python3 >/dev/null || { echo "Python 3.11+ is required"; exit 1; }
command -v npm >/dev/null || { echo "Node 18+ / npm is required"; exit 1; }

# ---- backend ------------------------------------------------------------
if [ ! -x "$PY" ]; then
    step "creating the Python virtualenv (backend/.venv)"
    python3 -m venv "$VENV"
fi

if [ "$SKIP_INSTALL" -eq 0 ]; then
    want="$(cat "$ROOT/backend/requirements.txt" "$ROOT/backend/requirements-ml.txt" 2>/dev/null | shasum -a 256 2>/dev/null | cut -d' ' -f1 || \
            cat "$ROOT/backend/requirements.txt" "$ROOT/backend/requirements-ml.txt" 2>/dev/null | sha256sum | cut -d' ' -f1)"
    have="$(cat "$STAMP" 2>/dev/null || true)"
    if [ "$want" != "$have" ]; then
        step "installing backend dependencies (the ML stack is ~2.5 GB the first time)"
        "$PY" -m pip install --disable-pip-version-check -q -r "$ROOT/backend/requirements.txt"
        "$PY" -m pip install --disable-pip-version-check -q -r "$ROOT/backend/requirements-ml.txt"
        printf '%s' "$want" > "$STAMP"
    else
        step "backend dependencies are current"
    fi
else
    step "skipping dependency install (--skip-install)"
fi

if [ ! -d "$ROOT/backend/app/ml/models/sentiment-classifier" ]; then
    warn "No fine-tuned model yet. The pipeline falls back to slower generic models."
    warn "Build the corpus and train everything with one command:"
    warn "    cd backend && .venv/bin/python -m app.ml.bootstrap"
fi
[ -f "$ROOT/backend/.env" ] || warn "backend/.env not found. Running on defaults (SQLite, no platform keys)."

# ---- frontend -----------------------------------------------------------
if [ "$SKIP_INSTALL" -eq 0 ] && [ ! -d "$ROOT/frontend/node_modules" ]; then
    step "installing frontend dependencies"
    (cd "$ROOT/frontend" && npm install --no-fund --no-audit)
fi

# ---- run ----------------------------------------------------------------
step "starting the API on http://localhost:$API_PORT"
( cd "$ROOT/backend" && PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 \
    "$PY" -m uvicorn app.main:app --port "$API_PORT" 2>&1 | sed 's/^/[api] /' ) &

step "starting the dashboard on http://localhost:$WEB_PORT"
( cd "$ROOT/frontend" && FORCE_COLOR=1 \
    npm run dev -- --port "$WEB_PORT" --strictPort 2>&1 | sed 's/^/[web] /' ) &

for _ in $(seq 1 180); do
    if curl -fsS "http://127.0.0.1:$API_PORT/api/health" >/dev/null 2>&1; then
        printf '\n  \033[32mSENTINEL is live\033[0m\n'
        printf '    dashboard   http://localhost:%s\n' "$WEB_PORT"
        printf '    API docs    http://localhost:%s/docs\n' "$API_PORT"
        printf '    sign in     suratpolice / Suratpolice@1234   (change before real use)\n\n'
        printf '  Ctrl+C stops both.\n\n'
        break
    fi
    sleep 1
done

wait

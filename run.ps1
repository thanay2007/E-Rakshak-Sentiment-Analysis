# SENTINEL — one-command local startup (Windows)
# Usage:  .\run.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "SENTINEL bootstrap" -ForegroundColor Cyan

# ── backend ──────────────────────────────────────────────────────────────
Write-Host "[1/4] using active Python environment..." -ForegroundColor Yellow

Write-Host "[2/4] installing backend deps (ML stack is ~2.5 GB on first run)..."
& python -m pip install -q -r "$root\backend\requirements.txt"
& python -m pip install -q -r "$root\backend\requirements-ml.txt"

if (-not (Test-Path "$root\backend\app\ml\models\threat-classifier") -or
    -not (Test-Path "$root\backend\app\ml\models\sentiment-classifier")) {
    Write-Host "NOTE: no fine-tuned models yet. Rebuild datasets + train both with ONE command:" -ForegroundColor Yellow
    Write-Host "      cd backend; python -m app.ml.bootstrap" -ForegroundColor Yellow
    Write-Host "      (until then, full mode uses slower generic models)" -ForegroundColor Yellow
}

Write-Host "[3/4] starting backend on http://localhost:8000 ..."
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "Set-Location '$root\backend'; python -m uvicorn app.main:app --port 8000"

# ── frontend ─────────────────────────────────────────────────────────────
if (-not (Test-Path "$root\frontend\node_modules")) {
    Write-Host "[4/4] installing frontend deps..." -ForegroundColor Yellow
    Push-Location "$root\frontend"; npm install; Pop-Location
} else { Write-Host "[4/4] node_modules exists" }

Write-Host "starting frontend on http://localhost:5173 ..."
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "Set-Location '$root\frontend'; npm run dev"

Start-Sleep -Seconds 3
Start-Process "http://localhost:5173"
Write-Host ""
Write-Host "SENTINEL is live -> http://localhost:5173  (API docs: http://localhost:8000/docs)" -ForegroundColor Green

# SENTINEL - one-command local startup (Windows)
#
#   .\run.ps1                 install what is missing, start both, open the app
#   .\run.ps1 -SkipInstall    straight to starting (fastest, once set up)
#   .\run.ps1 -NoBrowser      do not open a browser
#   .\run.ps1 -ApiPort 8001 -WebPort 5174
#
# Both services run as children of THIS window, with their output interleaved
# and labelled [api] / [web]. Ctrl+C stops both. Nothing is left running in a
# window you have to hunt for afterwards - the previous version spawned two
# detached PowerShell windows, which meant two things to close, two places to
# look for an error, and a backend still holding port 8000 after you thought
# you had stopped it.
#
# This file is deliberately plain ASCII and saved with a BOM. Windows
# PowerShell 5.1 reads a .ps1 without a BOM as ANSI, so a single em dash in a
# comment turns into a parse error three lines later - which is exactly how
# this script broke the first time.
#
# If Windows refuses to run it ("running scripts is disabled"), either
#   powershell -ExecutionPolicy Bypass -File .\run.ps1
# or allow local scripts once:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$NoBrowser,
    [int]$ApiPort = 8000,
    [int]$WebPort = 5173
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venv = Join-Path $root "backend\.venv"
$python = Join-Path $venv "Scripts\python.exe"
# Marker recording which requirements files were last installed. Without it
# every start pays ~15 s for pip to re-check a fully satisfied ML stack.
$stamp = Join-Path $venv ".deps-stamp"

$script:Procs = @()

function Write-Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Write-Warn($text) { Write-Host "    $text" -ForegroundColor Yellow }

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Get-RequirementsHash {
    $files = @("backend\requirements.txt", "backend\requirements-ml.txt")
    $text = ($files | ForEach-Object {
        $p = Join-Path $root $_
        if (Test-Path $p) { Get-Content $p -Raw }
    }) -join "`n"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($text)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    return [System.BitConverter]::ToString($sha.ComputeHash($bytes)).Replace("-", "")
}

# Starts a child process wired into this console: its stdout/stderr are read
# asynchronously and reprinted with a coloured tag, so one window shows both
# services and you can tell at a glance which one is complaining.
function Start-Child($label, $color, $file, $arguments, $workdir) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $file
    $psi.Arguments = $arguments
    $psi.WorkingDirectory = $workdir
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    # Both children speak UTF-8 (vite's arrows, and every Gujarati page name
    # the crawler logs). Without this they are decoded as the console codepage
    # and the log fills with mojibake.
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $psi.EnvironmentVariables["FORCE_COLOR"] = "1"
    $psi.EnvironmentVariables["PYTHONUNBUFFERED"] = "1"
    $psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8"

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    $proc.EnableRaisingEvents = $true

    $sink = {
        if ($EventArgs.Data) {
            Write-Host "[$($Event.MessageData.Label)] " -ForegroundColor $Event.MessageData.Color -NoNewline
            Write-Host $EventArgs.Data
        }
    }
    $meta = [pscustomobject]@{ Label = $label; Color = $color }
    Register-ObjectEvent -InputObject $proc -EventName OutputDataReceived `
        -Action $sink -MessageData $meta | Out-Null
    Register-ObjectEvent -InputObject $proc -EventName ErrorDataReceived `
        -Action $sink -MessageData $meta | Out-Null

    [void]$proc.Start()
    $proc.BeginOutputReadLine()
    $proc.BeginErrorReadLine()
    $script:Procs += $proc
    return $proc
}

function Stop-Children {
    foreach ($p in $script:Procs) {
        if ($p -and -not $p.HasExited) {
            # Kill the tree: uvicorn and vite both spawn children (the reloader,
            # esbuild), and killing only the parent leaves the port held.
            try { & taskkill.exe /PID $p.Id /T /F 2>$null | Out-Null } catch {}
        }
    }
    Get-EventSubscriber | Where-Object { $_.SourceObject -is [System.Diagnostics.Process] } |
        Unregister-Event -ErrorAction SilentlyContinue
}

function Wait-ForApi($url, $seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { return $true }
        } catch { Start-Sleep -Milliseconds 700 }
        if ($script:Procs | Where-Object { $_.HasExited }) { return $false }
    }
    return $false
}

Write-Host ""
Write-Host "  SENTINEL" -ForegroundColor Green -NoNewline
Write-Host "  -  Gujarat Police social-media intelligence"
Write-Host ""

# ---- prerequisites ------------------------------------------------------
if (-not (Test-Command "python")) {
    throw "Python is not on PATH. Install Python 3.11+ and reopen this terminal."
}
if (-not (Test-Command "npm")) {
    throw "Node.js/npm is not on PATH. Install Node 18+ and reopen this terminal."
}

# ---- backend ------------------------------------------------------------
if (-not (Test-Path $python)) {
    Write-Step "creating the Python virtualenv (backend\.venv)"
    python -m venv $venv
}

if (-not $SkipInstall) {
    $want = Get-RequirementsHash
    $have = if (Test-Path $stamp) { (Get-Content $stamp -Raw).Trim() } else { "" }
    if ($want -ne $have) {
        Write-Step "installing backend dependencies (the ML stack is ~2.5 GB the first time)"
        & $python -m pip install --disable-pip-version-check -q -r (Join-Path $root "backend\requirements.txt")
        & $python -m pip install --disable-pip-version-check -q -r (Join-Path $root "backend\requirements-ml.txt")
        if ($LASTEXITCODE -ne 0) { throw "pip install failed. See the output above." }
        Set-Content -Path $stamp -Value $want -Encoding utf8
    } else {
        Write-Step "backend dependencies are current"
    }
} else {
    Write-Step "skipping dependency install (-SkipInstall)"
}

$models = Join-Path $root "backend\app\ml\models"
if (-not (Test-Path (Join-Path $models "sentiment-classifier"))) {
    Write-Warn "No fine-tuned model yet. The pipeline falls back to slower generic models."
    Write-Warn "Build the corpus and train everything with one command:"
    Write-Warn "    cd backend; .venv\Scripts\python.exe -m app.ml.bootstrap"
}

if (-not (Test-Path (Join-Path $root "backend\.env"))) {
    Write-Warn "backend\.env not found. Running on defaults (SQLite, no platform keys)."
}

# ---- frontend -----------------------------------------------------------
if ((-not $SkipInstall) -and (-not (Test-Path (Join-Path $root "frontend\node_modules")))) {
    Write-Step "installing frontend dependencies"
    Push-Location (Join-Path $root "frontend")
    npm install --no-fund --no-audit
    $npmFailed = $LASTEXITCODE -ne 0
    Pop-Location
    if ($npmFailed) { throw "npm install failed. See the output above." }
}

# ---- run ----------------------------------------------------------------
try {
    Write-Step "starting the API on http://localhost:$ApiPort"
    Start-Child "api" "Magenta" $python `
        "-m uvicorn app.main:app --port $ApiPort" (Join-Path $root "backend") | Out-Null

    Write-Step "starting the dashboard on http://localhost:$WebPort"
    # Through cmd.exe on purpose: npm on Windows is npm.cmd, a batch file, and
    # CreateProcess cannot execute one ("not a valid application for this OS
    # platform"). taskkill /T later takes the cmd and the node under it.
    Start-Child "web" "Blue" $env:ComSpec `
        "/c npm run dev -- --port $WebPort --strictPort" (Join-Path $root "frontend") | Out-Null

    if (Wait-ForApi "http://127.0.0.1:$ApiPort/api/health" 180) {
        Write-Host ""
        Write-Host "  SENTINEL is live" -ForegroundColor Green
        Write-Host "    dashboard   http://localhost:$WebPort"
        Write-Host "    API docs    http://localhost:$ApiPort/docs"
        Write-Host "    sign in     suratpolice / Suratpolice@1234   (change before real use)"
        Write-Host ""
        Write-Host "  Ctrl+C stops both." -ForegroundColor DarkGray
        Write-Host ""
        if (-not $NoBrowser) { Start-Process "http://localhost:$WebPort" }
    } else {
        Write-Warn "the API did not answer /api/health in time. Its output is above, tagged [api]."
    }

    # Hold the window open while either service is alive. Ctrl+C lands in the
    # finally block below, which is what stops them.
    while ($script:Procs | Where-Object { -not $_.HasExited }) {
        Start-Sleep -Milliseconds 400
    }
    Write-Warn "a service exited on its own. Stopping the other."
}
finally {
    Write-Host ""
    Write-Step "stopping SENTINEL"
    Stop-Children
}

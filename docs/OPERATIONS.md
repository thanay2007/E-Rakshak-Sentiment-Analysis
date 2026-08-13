# Running and operating SENTINEL

## One command

```powershell
.\run.ps1                 # Windows
```
```bash
./run.sh                  # Linux / macOS
```

Both services run as children of **that one terminal**, with their output
interleaved and labelled `[api]` / `[web]`. Ctrl+C stops both, killing the
process trees — uvicorn's reloader and vite's esbuild are children, and killing
only the parents leaves the ports held.

```
  SENTINEL  -  Gujarat Police social-media intelligence

==> backend dependencies are current
==> starting the API on http://localhost:8000
==> starting the dashboard on http://localhost:5173
[web]   VITE v5.4.21  ready in 479 ms
[api] INFO:     Application startup complete.

  SENTINEL is live
    dashboard   http://localhost:5173
    API docs    http://localhost:8000/docs
    sign in     suratpolice / Suratpolice@1234   (change before real use)
```

The script creates the virtualenv if missing, installs dependencies **only when
`requirements*.txt` actually changed** (a hash stamp in `backend/.venv`, so a
normal start does not pay 15 seconds for pip to re-check a satisfied ML stack),
runs `npm install` if `node_modules` is missing, waits for `/api/health` to
answer, and then opens the browser.

| Flag | Effect |
|---|---|
| `-SkipInstall` / `--skip-install` | straight to starting — fastest once set up |
| `-NoBrowser` | do not open a browser |
| `-ApiPort` / `-WebPort` | move either service (`API_PORT` / `WEB_PORT` env vars on Unix) |

**If Windows refuses to run it** ("running scripts is disabled"):

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
# or, once:
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Two things about `run.ps1` worth knowing if you edit it: it is plain ASCII and
saved **with a BOM**, because Windows PowerShell 5.1 reads a BOM-less `.ps1` as
ANSI and one em dash in a comment becomes a parse error three lines later. And
the dashboard is launched through `cmd.exe /c npm`, because `npm` on Windows is
a batch file that `CreateProcess` cannot execute directly.

## Manual start

```bash
cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
cd frontend && npm run dev
```

## First-time setup beyond the app

```bash
cd backend
python -m app.ml.bootstrap        # datasets + both models + eval (long, one command)
python -m app.services.voice.bootstrap   # local neural voice weights (~336 MB)
```

Neither is required to start: without trained models the pipeline falls back to
generic ones and says so on the Settings page.

## Command-line tools

| Command (from `backend/`) | What it does |
|---|---|
| `python -m app.ml.bootstrap` | rebuild datasets, train both models, evaluate |
| `python -m app.ml.train_sentiment` | fine-tune MuRIL only |
| `python -m app.ml.train_baseline` | train the TF-IDF + LinearSVC model only |
| `python -m app.ml.evaluate` | end-to-end pipeline evaluation |
| `python -m app.ml.eval_sentiment` | per-language model report |
| `python -m app.ml.check_device` | GPU/CPU diagnostic ([GPU.md](GPU.md)) |
| `python -m app.ml.download_datasets` | raw public datasets only |
| `python -m app.ml.groq_augment` | LLM corpus augmentation (optional, resumable) |
| `python -m app.crawlers.facebook_login` | one-time Facebook login, visible browser |
| `python -m app.crawlers.facebook_discover` | find pages per city ([COLLECTION.md](COLLECTION.md)) |
| `python -m app.crawlers.instagrapi_login` | one-time Instagram login / `--verify` |
| `python -m app.crawlers.instagram_verify <handle>:<City>` | check a seed handle before adding it |
| `python -m app.crawlers.telegram_login` | generate a Telegram session string |
| `python -m app.crawlers.telegram_discover` | refresh the Telegram channel list |
| `python -m app.copy_db` | copy a SQLite corpus into Postgres/Supabase ([SUPABASE.md](SUPABASE.md)) |
| `python -m pytest tests/ -q` | the test suite |

## Configuration

Everything lives in `backend/.env` (gitignored); defaults and the reasoning
behind them are annotated in `backend/app/config.py`.

The settings you actually have to think about:

```env
# scope
TARGET_CITIES=["Surat","Ahmedabad","Vadodara","Rajkot"]
SIMULATION_ENABLED=false        # false = live data only
NLP_MODE=full                   # full | lite

# security — see docs/SECURITY.md
SECRET_KEY=
BOOTSTRAP_ADMIN_PASSWORD=
BIOMETRIC_ENCRYPTION_KEY=

# storage — see docs/SUPABASE.md
DATABASE_URL=

# platforms — see docs/COLLECTION.md
X_AUTH_TOKEN= / X_CT0=
REDDIT_CLIENT_ID= / REDDIT_CLIENT_SECRET=
TELEGRAM_API_ID= / TELEGRAM_API_HASH= / TELEGRAM_SESSION_STRING=
YOUTUBE_API_KEY=
FB_PAGE_IDS_RAW=["suratcitypolice:Surat"]
IG_SESSIONID=

# LLMs — see docs/LLM.md
GROQ_API_KEY= / GEMINI_API_KEY=
```

List settings take a **JSON array** in `.env`, not a comma-separated string.

## Health and status

| Surface | Shows |
|---|---|
| `GET /api/health` | liveness only — deliberately says nothing about configuration |
| `GET /api/admin/system` (admin) | per-platform online/offline **with the reason**, model status, LLM quota state |
| Settings page | the same, rendered |

A platform that holds credentials it cannot use reports **offline with a
reason**, which is the row an operator can act on. "Instagram: offline" with no
reason is indistinguishable from "Instagram: never set up".

## Database and migrations

`AUTO_MIGRATE=true` (default) runs `alembic upgrade head` at boot, so a fresh
clone and a fresh Supabase project both just work. Turn it off where migrations
should be a reviewed step run ahead of the deploy — with more than one worker
you want exactly one process applying them, not a race.

Nothing in the application deletes history on its own. Retention is an explicit
admin action.

## Ports

| Port | Service |
|---|---|
| 8000 | FastAPI (`/docs` for the OpenAPI UI) |
| 5173 | Vite dev server |

`run.ps1` passes `--strictPort`, so a port collision fails loudly instead of
silently moving the dashboard somewhere the API's CORS list does not name.

## Tests

```bash
cd backend && python -m pytest tests/ -q     # 365 tests
cd frontend && npm run test                  # 11 tests
cd frontend && npx tsc -b --noEmit           # typecheck
```

The backend suite never touches the network: Instagram's signed-out routes and
the discovered-account roster are both stubbed by autouse fixtures in
`tests/conftest.py`.

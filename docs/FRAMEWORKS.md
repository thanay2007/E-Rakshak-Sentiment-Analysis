# SENTINEL — Framework Guide

How each framework in the stack is used in this project, with the patterns verified
against current official documentation (fetched via Context7 from
fastapi.tiangolo.com, sqlmodel.tiangolo.com and the Vite v5 docs). File references
point into this repo.

---

## Backend

### FastAPI (`backend/app/main.py`, `backend/app/routers/`)

**How we use it**

- **Lifespan context manager** instead of the deprecated `@app.on_event("startup")`:
  [`main.py`](../backend/app/main.py) wraps startup/shutdown in one
  `@asynccontextmanager async def lifespan(app)` — it creates tables, seeds the
  watchlist and simulated history, starts the APScheduler loop, and on exit stops
  the scheduler. This is the pattern FastAPI's current docs recommend (the SQLModel
  tutorial still shows `on_event`; lifespan supersedes it).
- **Routers per domain**: `alerts`, `feed`, `network`, `reports`, `stats`,
  `trends`, `watchlist`, `ws` — each an `APIRouter` included into the app.
- **WebSocket endpoint** ([`routers/ws.py`](../backend/app/routers/ws.py)):
  `@router.websocket("/ws/live")` accepts the socket, registers it with a shared
  connection manager (`services/websocket_manager.py`), and catches
  `WebSocketDisconnect` to unregister — exactly the documented pattern:

  ```python
  @router.websocket("/ws/live")
  async def live(ws: WebSocket):
      await manager.connect(ws)        # accept + track
      try:
          while True:
              await ws.receive_text()  # keepalive; server pushes via manager
      except WebSocketDisconnect:
          manager.disconnect(ws)
  ```

  Broadcasts use `websocket.send_json(payload)` (text mode by default per the
  reference docs).
- **CORS middleware** allows the Vite dev origin (`http://localhost:5173`).

**Doc pointers**: [WebSockets](https://fastapi.tiangolo.com/advanced/websockets/) ·
[Lifespan events](https://fastapi.tiangolo.com/advanced/events/) ·
[Testing WebSockets](https://fastapi.tiangolo.com/advanced/testing-websockets/)

### SQLModel (`backend/app/models/`, `backend/app/database.py`)

**How we use it**

- Table models declared as `class X(SQLModel, table=True)` with
  `id: int | None = Field(default=None, primary_key=True)` and indexed columns via
  `Field(index=True)`.
- One engine created from `DATABASE_URL` (SQLite file by default —
  `connect_args={"check_same_thread": False}` is required for SQLite under
  FastAPI's threaded access, per the SQLModel docs; set
  `DATABASE_URL=postgresql+psycopg://…` to switch to Postgres with zero model
  changes).
- `SQLModel.metadata.create_all(engine)` at startup (`init_db()`), and a
  context-managed session helper (`session_scope()` — the `with Session(engine)`
  pattern from the docs, wrapped for commit/rollback).

**Doc pointers**: [SQLModel + FastAPI tutorial](https://sqlmodel.tiangolo.com/tutorial/fastapi/) ·
[Session with dependency](https://sqlmodel.tiangolo.com/tutorial/fastapi/session-with-dependency/)

### APScheduler (`backend/app/services/scheduler.py`)

- A single `crawl_tick` interval job (every 4 s in simulation) drives ingestion.
- Live platform APIs are protected by per-platform politeness gaps
  (`CRAWL_MIN_INTERVAL_SECONDS`, default 300 s; YouTube 900 s) so no official API
  is ever hammered — the scheduler tick is cheap, the adapters decide whether
  they're allowed to fire.

### Hugging Face Transformers (`backend/app/ml/`)

- Fine-tunes `google/muril-base-cased` twice (threat 4-way, sentiment 3-way) with
  the `Trainer` API, fp16 on GPU; models load once at startup (singleton) and fall
  back full → generic pretrained → lite lexicon so the app never crashes without
  models.
- Gotchas recorded in the repo memory: Windows MAX_PATH must be enabled for HF
  cache paths, and CUDA torch comes from the `cu128` index when a GPU is present.

---

## Frontend

### Vite 5 (`frontend/vite.config.ts`)

- Minimal config: `@vitejs/plugin-react` + fixed dev port 5173.
- **No dev proxy is configured** — the frontend talks to the backend's absolute
  URL (`http://localhost:8000`) from [`services/api.ts`](../frontend/src/services/api.ts),
  with CORS handled server-side. If you ever want same-origin calls instead, the
  documented pattern is:

  ```ts
  // vite.config.ts — dev-only; proxy does NOT apply to `vite build` output
  export default defineConfig({
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": { target: "http://localhost:8000", changeOrigin: true },
        "/ws":  { target: "ws://localhost:8000", ws: true }, // WebSocket proxying
      },
    },
  });
  ```

  (Per the Vite docs, `server.proxy` only affects the dev server — production
  serving needs a real reverse proxy.)
- `npm run build` runs `tsc -b && vite build` — type-check first, then bundle.

**Doc pointers**: [server.proxy](https://vite.dev/config/server-options#server-proxy) ·
[Building for production](https://vite.dev/guide/build)

### React 18 + React Router 6 (`frontend/src/`)

- `createRoot` in `main.tsx`; routes: `/` (Landing) and `/app/*` inside `Layout`
  (Sidebar + TopBar + Outlet).
- Data flows through two custom hooks only: `usePolling` (interval REST refresh
  via the typed `api.ts` client) and `useLive*` (WebSocket pushes from `ws.ts`,
  which reconnects automatically). Pages never fetch ad hoc.

### Tailwind CSS 3 (`frontend/tailwind.config.js`, `frontend/src/index.css`)

- Design tokens live in `theme.extend`: `base.*` surface scale, `accent` cyan
  (#14B8C4), and semantic `threat.*` colors (critical/inflammatory/fake/neutral).
- Reusable surfaces are `@apply`-based component classes in `index.css`
  (`.glass`, `.glass-hover`, `.shimmer`, `.bg-grid`) rather than long utility
  strings repeated per component.
- Native form controls (selects, range sliders, datetime pickers) are themed
  globally in `index.css` so every page inherits the same dark chrome.

### Animation & visualization

| Library | Where | Why |
|---|---|---|
| GSAP | `useGsapReveal`, `Landing.tsx` | timeline hero animation, staggered list reveals |
| Framer Motion | `Reports.tsx` modal, `AlertToasts` | enter/exit transitions with `AnimatePresence` |
| Recharts | `Dashboard.tsx`, `Trends.tsx` | sentiment area chart, platform bars, sparklines |
| d3-force | `NetworkGraph.tsx` | canvas force layout for the account interaction graph |
| lucide-react | everywhere | icon set |

---

## Version reference

| Package | Version | Notes |
|---|---|---|
| FastAPI + Uvicorn | see `backend/requirements.txt` | lifespan API, WebSocket support |
| SQLModel | see `backend/requirements.txt` | SQLite default, Postgres via `DATABASE_URL` |
| React / React DOM | ^18.3 | `createRoot`, concurrent features |
| React Router | ^6.26 | nested routes under `/app` |
| Vite | ^5.4 | dev server :5173 |
| Tailwind CSS | ^3.4 | JIT, custom tokens |
| TypeScript | ~5.6 | `tsc -b` in the build |
| GSAP | ^3.12 | context-scoped timelines |
| Framer Motion | ^11 | `AnimatePresence` modals |
| Recharts | ^2.13 | themed via `.recharts-*` CSS |
| d3-force | ^3 | canvas rendering, no DOM nodes |

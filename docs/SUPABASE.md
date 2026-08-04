# Storing the corpus in Supabase

By default SENTINEL keeps everything in `backend/sentinel.db`, a SQLite file.
That is fine for a demo and wrong for a deployment: the record lives on one
machine, there is no backup, and two officers on two laptops are looking at two
different databases.

Point `DATABASE_URL` at Supabase and the same schema, built by the same
migrations, is created there instead. There is no separate "Supabase mode" in
the code — one URL decides it.

## "Supabase" and "PostgreSQL" are the same thing here

Worth stating plainly because the connection string looks like it names a
different product: **Supabase is hosted PostgreSQL.** A Supabase project *is* a
Postgres database, with a REST API, auth and storage bolted on beside it.

So `postgresql+psycopg://...pooler.supabase.com...` is not "using Postgres
instead of Supabase" — it is the standard way to connect *to* Supabase's
database. `postgresql` names the wire protocol, `psycopg` the Python driver,
and `supabase.com` the server. Nothing else is involved and no second database
exists anywhere in this project.

The alternative would be reaching Supabase through its REST API with the
`sb_publishable_` / `sb_secret_` keys. This backend deliberately does not: that
path has no transactions, no joins, no aggregate queries and no migrations, so
every query in the application and the entire Alembic setup would have to be
thrown away and rewritten. Supabase itself recommends a direct connection for a
server-side application. The `sb_` keys are for browser and mobile clients
talking to Supabase without a backend — which is not this architecture.

## What gets stored

Every table, permanently:

| Table | Holds |
|---|---|
| `post` | every collected post — text, translation, language, sentiment, threat score, engagement, media, cluster id |
| `alert` | raised threats and their workflow state |
| `report` | generated incident/escalation reports and their PDF paths |
| `watchlistitem` | the terms steering the crawlers |
| `suspect` | registry records: identity, charges, handles, face templates |
| `user` | officer accounts, scrypt hashes, lockout and revocation state |
| `auditlog` | who did what, when, from where — **append-only** |
| `facesearchlog` | every biometric query run — **append-only** |

Worth stating plainly, because it was the question behind this change:

- **Nothing deletes on a timer.** No TTL, no rolling window, no row cap. The
  only deletion path is `POST /api/admin/purge`, which is admin-only and needs
  an explicit day count.
- **Re-collection de-duplicates instead of duplicating.** `post.content_hash`
  carries a UNIQUE index, so seeing the same post again is a no-op.
- **The audit tables cannot be rewritten at all** — `BEFORE UPDATE OR DELETE`
  triggers raise on both dialects (migration `0002`).

If the dashboard looks like it only holds recent posts, that is the *view* being
windowed — feed and trends default to 24 hours — not the store. Widen the window
on the page, or ask Sentinel for a longer one ("how is Surat looking this week").

## Migrations

`alembic/versions/` is the single source of truth for the schema. `create_all()`
is no longer used anywhere: it silently does nothing to a table that already
exists, which is how a column added to a model reaches a fresh database and
never reaches an existing one.

| Revision | What it does |
|---|---|
| `0001_baseline` | creates all eight tables and their indexes |
| `0002_append_only` | audit triggers — SQLite `RAISE(ABORT)`, Postgres plpgsql |
| `0003_legacy_indexes` | creates three indexes that pre-migration databases never got |

The API runs `alembic upgrade head` at boot (`AUTO_MIGRATE=true`, the default),
so a fresh clone and a fresh Supabase project both just work. Set
`AUTO_MIGRATE=false` where migrations should be a reviewed step run ahead of the
deploy — with more than one worker you want exactly one process applying them.

Manual use, from `backend/`:

```bash
alembic current                 # where is this database?
alembic upgrade head            # apply everything outstanding
alembic upgrade head --sql      # print the DDL instead of running it, for review
alembic downgrade -1            # step back one
alembic revision --autogenerate -m "add x to post"   # after changing a model
```

`alembic.ini` has **no** URL in it — `env.py` reads `DATABASE_URL` from
`app.config`, so the migrations and the running API can never point at different
databases.

### After changing a model

Autogenerate, then *read the file it produced* before committing it. Alembic
detects added and removed columns reliably; it guesses at renames (it sees a
drop plus an add, which loses the data) and it cannot know about data
backfills.

## Setting up Supabase

1. **Create the project** at [supabase.com](https://supabase.com). `ap-south-1`
   (Mumbai) is closest for a Gujarat deployment.

2. **Copy the connection string.** Project Settings → Database → Connection
   string → URI. Use the **session pooler** entry (port `5432`).

3. **Rewrite the scheme** to `postgresql+psycopg://` so SQLAlchemy picks
   psycopg 3, and put it in `backend/.env`:

   ```dotenv
   DATABASE_URL=postgresql+psycopg://postgres.abcdefgh:YOUR-PASSWORD@aws-0-ap-south-1.pooler.supabase.com:5432/postgres?sslmode=require
   ```

   Percent-encode any of `@ : / ? # [ ] %` in the password, or the URL parser
   reads it as part of the host.

4. **Install the driver** (already in `requirements.txt`):

   ```bash
   cd backend && pip install -r requirements.txt
   ```

5. **Start the backend.** It runs every migration, provisions the administrator
   and seeds the watchlist:

   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

   Look for `database ready (postgres) at revision 0003_legacy_indexes`. Admin
   Panel → Security Posture flips "Durable shared database" to a pass.

### Pooler choice

Use the **session pooler (5432)**. The transaction pooler (6543) does not hold a
session across statements, which breaks SQLAlchemy's connection-scoped state and
Alembic's migration transaction. If you must use 6543, add
`?prepare_threshold=0` and expect rough edges.

`pool_pre_ping` is on by default because Supabase drops idle connections —
without it the first request after a quiet period fails with a stale-connection
error instead of transparently reconnecting.

## Moving the existing SQLite data across

The schema is identical on both sides, so this is a straight copy. Run it with
`DATABASE_URL` already pointing at Supabase, from `backend/`:

```python
# migrate_to_supabase.py — run once
from sqlmodel import Session, create_engine, select
from app import models
from app.database import engine as target, init_db

init_db()                                    # migrations create the schema first
source = create_engine("sqlite:///sentinel.db")

# AuditLog first and once: after 0002 the triggers refuse UPDATE, and `merge`
# on an existing row is an UPDATE. Everything else is safely re-runnable.
TABLES = [models.AuditLog, models.FaceSearchLog, models.User, models.Post,
          models.Alert, models.WatchlistItem, models.Report, models.Suspect]

with Session(source) as src, Session(target) as dst:
    for table in TABLES:
        rows = src.exec(select(table)).all()
        for row in rows:
            if table is models.AuditLog:
                dst.add(table(**row.model_dump()))      # insert only
            else:
                dst.merge(table(**row.model_dump()))    # re-runnable
        dst.commit()
        print(f"{table.__name__}: {len(rows)}")
```

If the audit copy is interrupted partway, clear `auditlog` on the Supabase side
before retrying — you cannot `merge` over rows the triggers protect. That is the
guarantee working as intended, not a bug.

## Row Level Security

Supabase enables RLS on tables created through its dashboard, but **not** on
tables created by an external client like Alembic. These tables are reached only
by the backend using the Postgres role in `DATABASE_URL`; the browser never
talks to Supabase directly and no anon key is ever issued. Authorisation happens
in `app/security/deps.py` on every request.

If you later expose Supabase's REST API over these tables, enable RLS first.
Until then, the control is that nothing but the backend holds the credential.

## Backups

Supabase takes daily backups on paid plans; the free tier does not. For a
deployment holding case data, either move to a plan with point-in-time recovery
or schedule `pg_dump` — an append-only audit trail is only as durable as the
database it is appended to.

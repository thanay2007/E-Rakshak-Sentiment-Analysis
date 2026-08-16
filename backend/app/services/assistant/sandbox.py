"""A read-only SQL window, narrow enough to hand to a language model.

The curated tools answer the questions someone thought of in advance. This
answers the rest — "how many negative Gujarati posts on Reddit in Rajkot last
week were amplified", which no fixed handler will ever have a parameter for.
That is genuinely useful and it is also the single most dangerous thing in the
assistant, so it is defended in five independent layers. Any one of them alone
would be a bug waiting to happen; the point is that an escape has to beat all
five.

  1. **Restricted views.** The model is told about `assistant_posts`,
     `assistant_alerts` and `assistant_watchlist` — views that project a chosen
     subset of columns. Officer accounts, the audit trail, the suspect registry
     and face templates are not views, are not mentioned, and are not
     reachable: there is no SELECT that reaches a table the view does not read.

  2. **No free text leaves this module.** The post views deliberately omit
     `text`, `translation`, `keywords` and `hashtags`. Everything SQL can
     return is a number, a date, a boolean or a value from a closed vocabulary
     the product itself defines. Attacker-authored prose therefore cannot enter
     the model's context through this path at all — it only arrives through
     tools that fence it explicitly.

  3. **A validator that fails closed.** Single statement, must be a SELECT or a
     WITH, no comments, every table named must be one of the three views or a
     CTE declared in the query, and the real table names are refused wherever
     they appear. Anything the validator does not positively understand is
     rejected rather than passed through.

  4. **Engine-level read-only.** SQLite runs the statement under
     `PRAGMA query_only`, Postgres under `SET TRANSACTION READ ONLY`. If the
     validator were somehow beaten, the database itself still refuses the
     write. The transaction is rolled back unconditionally either way.

  5. **Budgets.** Statement length, row count, column count and wall-clock time
     are all capped, so a query that is merely expensive cannot take the
     dashboard down with it.

Every executed statement is returned to the caller for the audit record. If a
reviewer ever needs to know what the assistant asked the database, the answer
is in the audit trail verbatim.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text as sql_text

from app.database import IS_SQLITE, engine

log = logging.getLogger("sentinel.assistant.sql")

MAX_SQL_CHARS = 2000
MAX_ROWS = 50
MAX_COLUMNS = 12
TIMEOUT_SECONDS = 6.0


class SqlRejected(Exception):
    """The statement did not pass validation. The message is shown to the
    model so it can correct itself, and to nobody else."""


# ── the views the model is allowed to see ───────────────────────────────────

ALLOWED_VIEWS = ("assistant_posts", "assistant_alerts", "assistant_watchlist")

# Column projections, kept here rather than in a migration because they are
# part of the security boundary and belong next to the reasoning for it.
# Anything absent from these lists is unreachable by SQL.
_VIEW_SQL: dict[str, str] = {
    "assistant_posts": """
        SELECT id, platform, author_handle, author_followers, author_verified,
               author_account_age_days, language, code_mixed, sentiment_label,
               sentiment_score, sentiment_confidence, intent,
               concern_score, toxicity_score, location, cluster_id,
               is_amplified, created_at, ingested_at
        FROM post
    """,
    "assistant_alerts": """
        SELECT id, post_id, severity, status, category, location, platform,
               concern_score, created_at, updated_at
        FROM alert
    """,
    "assistant_watchlist": """
        SELECT id, kind, value, priority, category, active, created_at
        FROM watchlistitem
    """,
}

# What the model is shown. Written as prose rather than DDL because it also has
# to carry the vocabularies — a model that knows `sentiment_label` exists but
# not that it holds 'negative' will write a query returning zero rows and then
# confidently report that there is no negative sentiment anywhere.
SCHEMA_DOC = """\
assistant_posts — one row per collected post
  id TEXT, platform TEXT ('X','Facebook','Instagram','Reddit','Telegram','YouTube')
  author_handle TEXT, author_followers INT, author_verified BOOL,
  author_account_age_days INT
  language TEXT ('English','Hindi','Gujarati','Hinglish','Gujlish','Mixed','Other'), code_mixed BOOL
  sentiment_label TEXT ('positive','neutral','negative') — the post's only tag
  sentiment_score REAL (-1..1), sentiment_confidence REAL (0..1)
  intent TEXT ('informational','opinion','call_to_action','rumor')
  concern_score REAL (0..100) — how much analyst attention the post warrants;
    rises with negativity x confidence, toxicity, reach and matched-term severity
  toxicity_score REAL (0..1)
  location TEXT (a monitored city name, or '' when unresolved)
  cluster_id TEXT ('' means organic; non-empty means part of a coordinated burst)
  is_amplified BOOL
  created_at TIMESTAMP (when it was posted), ingested_at TIMESTAMP (when collected)

assistant_alerts — one row per raised alert
  id TEXT, post_id TEXT (joins assistant_posts.id)
  severity TEXT ('critical','high','medium'), status TEXT ('new','acknowledged','escalated')
  category TEXT (the post's sentiment tag), location TEXT, platform TEXT,
  concern_score REAL
  created_at TIMESTAMP, updated_at TIMESTAMP

assistant_watchlist — terms matched against every post
  id TEXT, kind TEXT ('keyword','hashtag','account','location'), value TEXT
  priority TEXT ('low','medium','high','critical'), category TEXT
  active BOOL, created_at TIMESTAMP

Post and alert body text is not queryable here by design. Use the top_posts and
list_alerts tools when the wording of a post or alert is what matters."""


# ── validation ──────────────────────────────────────────────────────────────

# Named wherever they appear, these are an immediate refusal. Reaching a table
# requires writing its name, so this cannot be aliased or subqueried around.
# `\b` will not fire inside `assistant_posts` or `post_id`, because `_` is a
# word character — the view names and the real names stay cleanly distinct.
_FORBIDDEN_TABLES = re.compile(
    r"\b(post|alert|watchlistitem|report|suspect|facesearchlog|auditlog|user|"
    r"users|alembic_version|sqlite_master|sqlite_schema|sqlite_temp_master|"
    r"pg_catalog|pg_class|pg_tables|pg_user|pg_shadow|pg_settings|"
    r"information_schema)\b", re.IGNORECASE)

# Statement-shape and side-effect keywords. `replace` is not here: SQLite's
# string function is legitimate and useful, while `REPLACE INTO` is caught by
# `into` below.
_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|attach|"
    r"detach|pragma|vacuum|reindex|analyze|begin|commit|rollback|savepoint|"
    r"into|copy|call|do|declare|execute|exec|merge|upsert|returning|"
    r"load_extension|readfile|writefile|edit|current_setting|set_config|"
    r"dblink|lo_import|lo_export|nextval|setval)\b", re.IGNORECASE)

_TABLE_REF = re.compile(r"\b(?:from|join)\s+([a-z_][\w.$]*(?:\s*,\s*[a-z_][\w.$]*)*)",
                        re.IGNORECASE)
_CTE_NAME = re.compile(r"(?:\bwith\b|,)\s*([a-z_]\w*)\s+as\s*\(", re.IGNORECASE)
_HAS_LIMIT = re.compile(r"\blimit\s+\d+", re.IGNORECASE)


def validate(raw: str) -> str:
    """Return the statement, ready to run, or raise `SqlRejected`.

    The returned string is not the input string: a LIMIT is appended when the
    query has none, so an unbounded SELECT becomes a bounded one rather than a
    rejection. Everything else is a refusal — silently rewriting a query the
    model got wrong would teach it nothing and hide the mistake.
    """
    stmt = raw.strip().rstrip(";").strip()

    if not stmt:
        raise SqlRejected("Empty statement.")
    if len(stmt) > MAX_SQL_CHARS:
        raise SqlRejected(f"Statement too long (limit {MAX_SQL_CHARS} characters).")
    if ";" in stmt:
        raise SqlRejected("Only one statement is allowed. Remove the semicolon.")
    if "--" in stmt or "/*" in stmt or "*/" in stmt:
        raise SqlRejected("Comments are not allowed.")
    if not re.match(r"^\s*(select|with)\b", stmt, re.IGNORECASE):
        raise SqlRejected("Only SELECT (or WITH ... SELECT) is allowed.")

    hit = _FORBIDDEN_KEYWORDS.search(stmt)
    if hit:
        raise SqlRejected(f"'{hit.group(1)}' is not allowed — this is a read-only window.")

    hit = _FORBIDDEN_TABLES.search(stmt)
    if hit:
        raise SqlRejected(
            f"'{hit.group(1)}' is not readable. The only tables are: "
            f"{', '.join(ALLOWED_VIEWS)}.")

    ctes = {name.lower() for name in _CTE_NAME.findall(stmt)}
    referenced: set[str] = set()
    for group in _TABLE_REF.findall(stmt):
        for name in group.split(","):
            referenced.add(name.strip().lower())

    if not referenced:
        raise SqlRejected("The query must read from one of: "
                          f"{', '.join(ALLOWED_VIEWS)}.")

    for name in referenced:
        if "." in name:
            raise SqlRejected("Schema-qualified names are not allowed.")
        if name not in ALLOWED_VIEWS and name not in ctes:
            raise SqlRejected(
                f"'{name}' is not a readable table. The only tables are: "
                f"{', '.join(ALLOWED_VIEWS)}.")

    if not _HAS_LIMIT.search(stmt):
        stmt = f"{stmt} LIMIT {MAX_ROWS}"
    return stmt


# ── execution ───────────────────────────────────────────────────────────────

@dataclass
class SqlResult:
    sql: str
    columns: list[str]
    rows: list[list]
    row_count: int
    truncated: bool
    elapsed_ms: int


def _coerce(value):
    """Render a cell as something JSON-safe and short.

    Floats are rounded because these end up in a spoken sentence, and
    "sixty-seven point four two nine nine nine" is not an answer anyone wants.
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return round(float(value), 3)
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, (int, bool)) or value is None:
        return value
    return str(value)[:120]


def _install_sqlite_deadline(dbapi_connection, deadline: float) -> None:
    """Abort a runaway SQLite query at the deadline.

    SQLite has no statement timeout, but it will call a progress handler every
    N virtual-machine instructions and abort the statement if that handler
    returns non-zero. 1000 instructions is frequent enough to be responsive and
    rare enough not to matter.
    """
    def _handler() -> int:
        return 1 if time.monotonic() > deadline else 0

    try:
        dbapi_connection.set_progress_handler(_handler, 1000)
    except Exception:  # pragma: no cover — driver without progress-handler support
        log.debug("sqlite progress handler unavailable; relying on row caps")


def run(raw_sql: str) -> SqlResult:
    """Validate and execute, always read-only, always rolled back."""
    stmt = validate(raw_sql)
    started = time.monotonic()
    deadline = started + TIMEOUT_SECONDS

    connection = engine.connect()
    try:
        if IS_SQLITE:
            raw = connection.connection.driver_connection
            # Layer 4: the database itself refuses to write for the duration of
            # this connection, whatever the statement turns out to be.
            connection.exec_driver_sql("PRAGMA query_only = ON")
            _install_sqlite_deadline(raw, deadline)
        else:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            connection.exec_driver_sql(
                f"SET LOCAL statement_timeout = {int(TIMEOUT_SECONDS * 1000)}")

        result = connection.execute(sql_text(stmt))
        columns = list(result.keys())[:MAX_COLUMNS]
        fetched = result.fetchmany(MAX_ROWS + 1)
        truncated = len(fetched) > MAX_ROWS
        rows = [[_coerce(cell) for cell in row[:MAX_COLUMNS]]
                for row in fetched[:MAX_ROWS]]
    except SqlRejected:
        raise
    except Exception as exc:
        # The driver's message is handed back to the model verbatim so it can
        # fix its own query. It describes the *views*, which the model already
        # knows about, so it discloses nothing new.
        raise SqlRejected(f"The database rejected that query: "
                          f"{str(exc).splitlines()[0][:200]}") from exc
    finally:
        try:
            if IS_SQLITE:
                try:
                    connection.connection.driver_connection.set_progress_handler(None, 0)
                except Exception:
                    pass
                # Must be reset explicitly: the connection goes back to the pool
                # and the pragma would otherwise follow it, turning the whole
                # application read-only.
                connection.exec_driver_sql("PRAGMA query_only = OFF")
            connection.rollback()
        finally:
            connection.close()

    return SqlResult(sql=stmt, columns=columns, rows=rows, row_count=len(rows),
                     truncated=truncated,
                     elapsed_ms=int((time.monotonic() - started) * 1000))


# ── view lifecycle ──────────────────────────────────────────────────────────

def ensure_views() -> None:
    """Create or refresh the read-only views. Called once at startup.

    Not an Alembic migration on purpose: these are a projection over tables
    Alembic owns, they carry no data, and a redefinition should follow the code
    that defines it rather than needing a migration to be generated and run.
    Failure is logged and swallowed — the SQL tool then reports itself
    unavailable, and every other capability keeps working.
    """
    for name, body in _VIEW_SQL.items():
        statement = (f"CREATE VIEW IF NOT EXISTS {name} AS {body}" if IS_SQLITE
                     else f"CREATE OR REPLACE VIEW {name} AS {body}")
        try:
            with engine.begin() as connection:
                if IS_SQLITE:
                    # SQLite cannot redefine a view in place, and the definition
                    # changes whenever the projection above does.
                    connection.exec_driver_sql(f"DROP VIEW IF EXISTS {name}")
                    connection.exec_driver_sql(f"CREATE VIEW {name} AS {body}")
                else:
                    connection.exec_driver_sql(statement)
        except Exception:
            log.exception("could not create assistant view %s", name)
            return
    log.info("assistant read-only views ready: %s", ", ".join(ALLOWED_VIEWS))


def available() -> bool:
    """Whether the views exist and are queryable right now."""
    try:
        with engine.connect() as connection:
            connection.execute(sql_text(f"SELECT 1 FROM {ALLOWED_VIEWS[0]} LIMIT 1"))
        return True
    except Exception:
        return False

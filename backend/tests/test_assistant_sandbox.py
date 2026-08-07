"""The SQL window's walls.

The assistant can write SQL, which is the most useful and the most dangerous
thing it does. `sandbox.py` defends that in five layers; this file tests the
one that is pure logic and can be tested without a database — the validator —
plus the two structural invariants that no amount of clever SQL can move.

The cases are grouped by what an escape would actually get you, rather than by
SQL syntax, because that is how someone probing this would think about it.

Run:  cd backend && python -m pytest tests/ -q
"""
from __future__ import annotations

import pytest

from app.services.assistant import sandbox, tools

ALLOWED = [
    "SELECT COUNT(*) FROM assistant_posts",
    "SELECT platform, COUNT(*) FROM assistant_posts GROUP BY platform",
    "select location, avg(threat_score) from assistant_posts group by location",
    "WITH recent AS (SELECT * FROM assistant_posts) SELECT COUNT(*) FROM recent",
    "SELECT p.platform, a.severity FROM assistant_posts p "
    "JOIN assistant_alerts a ON a.post_id = p.id",
    "SELECT kind, COUNT(*) FROM assistant_watchlist GROUP BY kind",
    # A trailing semicolon is how a person writes SQL and is not an attack.
    "SELECT COUNT(*) FROM assistant_posts;",
]

# Grouped by the thing the escape would reach.
REACHES_A_FORBIDDEN_TABLE = [
    "SELECT * FROM user",
    "SELECT * FROM users",
    "SELECT * FROM auditlog",
    "SELECT * FROM suspect",
    "SELECT * FROM facesearchlog",
    "SELECT * FROM post",
    "SELECT * FROM alert",
    "SELECT * FROM sqlite_master",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM pg_catalog.pg_tables",
    # Reached sideways rather than head-on.
    "SELECT * FROM assistant_posts UNION SELECT * FROM suspect",
    "SELECT (SELECT COUNT(*) FROM auditlog) FROM assistant_posts",
    "SELECT * FROM assistant_posts, user",
    "WITH x AS (SELECT * FROM user) SELECT * FROM x",
    "SELECT * FROM main.assistant_posts",
]

WRITES = [
    "DELETE FROM assistant_posts",
    "UPDATE assistant_posts SET threat_score = 0",
    "INSERT INTO assistant_posts VALUES (1)",
    "DROP VIEW assistant_posts",
    "CREATE TABLE evil AS SELECT * FROM assistant_posts",
    "SELECT * INTO evil FROM assistant_posts",
    "SELECT * FROM assistant_posts; DROP TABLE post",
    "TRUNCATE assistant_posts",
]

TOUCHES_THE_ENGINE = [
    "PRAGMA table_info(post)",
    "SELECT load_extension('evil.so')",
    "SELECT readfile('/etc/passwd')",
    "SELECT current_setting('is_superuser')",
    "VACUUM",
    # Comments are how a second statement gets smuggled past a naive parser.
    "SELECT COUNT(*) FROM assistant_posts -- and something else",
    "SELECT /* sneaky */ COUNT(*) FROM assistant_posts",
]


@pytest.mark.parametrize("statement", ALLOWED)
def test_ordinary_analytics_are_allowed(statement):
    assert sandbox.validate(statement)


@pytest.mark.parametrize("statement", REACHES_A_FORBIDDEN_TABLE)
def test_no_route_to_a_table_outside_the_views(statement):
    with pytest.raises(sandbox.SqlRejected):
        sandbox.validate(statement)


@pytest.mark.parametrize("statement", WRITES)
def test_nothing_that_writes_is_accepted(statement):
    with pytest.raises(sandbox.SqlRejected):
        sandbox.validate(statement)


@pytest.mark.parametrize("statement", TOUCHES_THE_ENGINE)
def test_engine_level_escapes_are_refused(statement):
    with pytest.raises(sandbox.SqlRejected):
        sandbox.validate(statement)


def test_an_unbounded_select_is_bounded_rather_than_rejected():
    """A missing LIMIT is a modelling slip, not an attack, and rejecting it
    just costs a round trip. A LIMIT the query already has is left alone."""
    assert f"LIMIT {sandbox.MAX_ROWS}" in sandbox.validate(
        "SELECT * FROM assistant_posts")
    assert sandbox.validate("SELECT * FROM assistant_posts LIMIT 3").endswith("LIMIT 3")


def test_an_overlong_statement_is_refused():
    with pytest.raises(sandbox.SqlRejected):
        sandbox.validate("SELECT * FROM assistant_posts WHERE id IN ("
                         + ",".join(["'x'"] * 1000) + ")")


# ── structural invariants ───────────────────────────────────────────────────

def test_post_and_alert_body_text_is_not_projected_into_any_view():
    """The strongest guarantee this module makes: attacker-authored prose
    cannot enter the model's context through SQL, because no view exposes a
    column containing it. If someone adds `text` to a projection, this fails
    and the guarantee needs restating rather than quietly weakening."""
    for name, definition in sandbox._VIEW_SQL.items():
        projection = definition.lower().split("from")[0]
        for column in ("text", "translation", "summary", "title", "keywords",
                       "notes", "password_hash", "face_templates", "photo_thumb"):
            assert f" {column}" not in projection and f"{column}," not in projection, (
                f"view {name} projects a free-text or sensitive column: {column}")


def test_the_views_never_read_a_sensitive_table():
    for name, definition in sandbox._VIEW_SQL.items():
        reads = definition.lower().split("from")[1].strip()
        assert reads in ("post", "alert", "watchlistitem"), (
            f"view {name} reads an unexpected table: {reads}")


def test_the_schema_shown_to_the_model_names_only_the_allowed_views():
    """The model plans its query from `SCHEMA_DOC`. If that document mentions a
    table the validator will refuse, every query it writes fails and it has no
    way to learn why."""
    for view in sandbox.ALLOWED_VIEWS:
        assert view in sandbox.SCHEMA_DOC
    for forbidden in ("auditlog", "suspect", "facesearchlog", "password"):
        assert forbidden not in sandbox.SCHEMA_DOC.lower()


# ── rank gating ─────────────────────────────────────────────────────────────

def test_no_tool_can_write():
    """The registry's central claim. A tool whose name suggests mutation is a
    review failure, not a runtime one — catch it here."""
    forbidden = ("delete", "update", "create", "set_", "purge", "acknowledge",
                 "escalate", "export", "send", "write", "remove", "assign")
    for tool in tools.TOOLS:
        assert not any(word in tool.name for word in forbidden), (
            f"tool {tool.name} sounds like it mutates — the voice channel is "
            f"read-only by construction")


def test_rank_filters_the_tool_list_and_the_call():
    """Two separate checks, deliberately duplicated in the source. This asserts
    they agree: a tool absent from an analyst's list must also refuse to run
    for an analyst."""
    from app.models import User

    analyst_tools = {t.name for t in tools.for_role("analyst")}
    admin_tools = {t.name for t in tools.for_role("admin")}
    assert analyst_tools <= admin_tools

    for name in admin_tools - analyst_tools:
        result = tools.invoke(
            name, {},
            tools.ToolContext(session=None, user=User(username="a", role="analyst")))
        assert "error" in result.payload


def test_an_unknown_tool_name_is_refused_rather_than_guessed():
    from app.models import User

    result = tools.invoke(
        "read_officer_accounts", {},
        tools.ToolContext(session=None, user=User(username="a", role="admin")))
    assert "error" in result.payload


def test_navigation_targets_come_from_a_fixed_table():
    """The model picks a label; the label is resolved here. A path never
    travels from the model to the browser, so a poisoned answer cannot send an
    officer anywhere."""
    from app.models import User

    ctx = tools.ToolContext(session=None, user=User(username="a", role="analyst"))
    assert tools.invoke("navigate", {"page": "alerts"}, ctx).navigate == "/app/alerts"
    # Anything not in the table opens nothing at all.
    for hostile in ("https://evil.example.com", "//evil.example.com",
                    "/app/../../etc/passwd", "javascript:alert(1)"):
        assert tools.invoke("navigate", {"page": hostile}, ctx).navigate is None

"""Alembic environment.

The schema this project runs on is defined by the migrations in `versions/`,
not by `SQLModel.metadata.create_all()`. That distinction is the whole point:
create_all() silently does nothing to a table that already exists, so a column
added to a model after the first boot never reaches an existing database and
the app dies on "no such column" somewhere far away from the cause.

Two deliberate choices:

  • The URL comes from `app.config.settings`, never from alembic.ini. One
    DATABASE_URL drives the API and the migrations, so `alembic upgrade head`
    cannot quietly migrate a different database than the one being served —
    which, when the two are SQLite-on-disk and Supabase, is a very easy mistake
    to make and a very confusing one to debug.

  • `render_as_batch` is on for SQLite. SQLite cannot ALTER a column or drop a
    constraint; batch mode rewrites the table instead. Without it every
    migration beyond "add a nullable column" fails on the default database.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# Importing the package registers every table on SQLModel.metadata. Import the
# package rather than a hand-listed set of classes: a model added later is then
# picked up automatically instead of being silently missing from autogenerate.
from app import models  # noqa: F401
from app.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

def _ini_safe(url: str) -> str:
    """Escape % for configparser, which owns alembic.ini.

    A password containing a reserved URL character has to be percent-encoded
    ("@" -> "%40"), and configparser then reads that % as the start of its own
    `%(name)s` interpolation and raises. Doubling it means "a literal %", and
    configparser un-doubles it on read, so the URL SQLAlchemy finally receives
    is unchanged. Without this, any password with @ : / ? # in it breaks every
    alembic command while the app itself connects fine — a confusing split.
    """
    return url.replace("%", "%%")


config.set_main_option("sqlalchemy.url", _ini_safe(settings.DATABASE_URL))

target_metadata = SQLModel.metadata

IS_SQLITE = settings.DATABASE_URL.startswith("sqlite")


def _options() -> dict:
    return {
        "target_metadata": target_metadata,
        "compare_type": True,
        "compare_server_default": True,
        "render_as_batch": IS_SQLITE,
    }


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it — `alembic upgrade head --sql`.

    Useful when a DBA has to review the DDL before it touches a production
    database, which is the normal arrangement for anything holding case data.
    """
    # The raw URL here, not the ini-escaped one — this goes straight to
    # SQLAlchemy rather than through configparser.
    context.configure(
        url=settings.DATABASE_URL,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_options(),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = context.config.attributes.get("connection", None)

    if connectable is not None:
        # Reusing a connection handed in by the caller — this is how
        # app/database.py runs migrations at boot without opening a second
        # engine against the same database.
        context.configure(connection=connectable, **_options())
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with engine.connect() as connection:
        context.configure(connection=connection, **_options())
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

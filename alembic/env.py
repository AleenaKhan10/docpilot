"""
Alembic environment.

Wires Alembic to:
  - The DATABASE_URL from settings (.env-driven). We pass it directly to
    create_engine() rather than via config.set_main_option(), because the
    URL-encoded password (containing `%25`) breaks ConfigParser
    interpolation.
  - The SQLAlchemy declarative_base() Base from our models, so
    `alembic revision --autogenerate` can diff DB ↔ code.
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import create_engine, pool

from alembic import context

# Make the project root importable so we can pull in our models + settings.
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from core.config import settings  # noqa: E402
from models import Base  # noqa: E402  — registers all model imports

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _db_url() -> str:
    if not settings.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    return settings.DATABASE_URL


def run_migrations_offline() -> None:
    context.configure(
        url=_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_db_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

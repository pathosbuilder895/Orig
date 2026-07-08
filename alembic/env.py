"""Alembic environment — LIVE pilot schema (WS-6 P2, ADR-006).

Targets the live 16-table metadata in ``original/db/models/live.py``
(``LiveBase.metadata``), NOT the dormant v1 ``original.db.base.Base``.
The 7 stale v1 revisions live in ``alembic/versions_v1_archive/`` — readable,
but off the migration path.

URL resolution order:
1. ``DATABASE_URL`` environment variable (Render / CI / local override).
2. The ``sqlalchemy.url`` default in ``alembic.ini`` (local postgres).
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Import ONLY the live models so exactly the 16 live tables register with
# the target metadata. (Importing the v1 models would not collide — they use
# a separate MetaData — but they are not alembic's concern anymore.)
from original.db.models.live import LiveBase

# This is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata — the LIVE schema
target_metadata = LiveBase.metadata

# DATABASE_URL env var wins over the alembic.ini fallback default.
_env_url = os.environ.get("DATABASE_URL")
if _env_url:
    config.set_main_option("sqlalchemy.url", _env_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = config.get_main_option("sqlalchemy.url")
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""Alembic environment configuration.

Wires sportsbet.config.settings into Alembic so the database URL is never
hardcoded in alembic.ini. target_metadata is set from ORM Base.metadata so
autogenerate can inspect the model state (though migrations are hand-written).
"""

import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Ensure src/ is on sys.path so sportsbet package is importable when running
# `alembic upgrade head` from the project root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sportsbet.config import settings  # noqa: E402
from sportsbet.db.models import Base  # noqa: E402

# Alembic Config object — provides access to values within the .ini file.
config = context.config

# Set the database URL dynamically from settings (never from alembic.ini).
config.set_main_option("sqlalchemy.url", settings.database_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ORM metadata for autogenerate support and migration context.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL without a live connection)."""
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
    """Run migrations in 'online' mode (apply to live database)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

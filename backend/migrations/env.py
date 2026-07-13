"""Alembic environment.

Migrations run as the database owner, on Neon's DIRECT endpoint.

Two constraints that are easy to get wrong:

  * **Direct endpoint, not pooled.** Alembic takes advisory locks and relies on
    session-level state; PgBouncer's transaction mode does not provide either.

  * **Never on application startup.** N replicas racing `alembic upgrade head`
    deadlock, or worse, half-apply. Migrations are a separate, deliberate step.

Autogenerate is deliberately not used for RLS. It cannot see policies, GRANTs,
FORCE ROW LEVEL SECURITY, or roles -- so schema drift on exactly the objects
that enforce tenant isolation is guaranteed. That is why the startup guards in
platform/db/guards.py exist: they turn silent drift into a failed deploy.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = os.environ.get("DIALETIQ_MIGRATION_DATABASE_URL") or os.environ.get("DIALETIQ_DATABASE_URL")
if not url:
    sys.exit(
        "DIALETIQ_MIGRATION_DATABASE_URL is not set.\n"
        "It must be Neon's DIRECT connection string (the host WITHOUT `-pooler`), "
        "using the owner role."
    )

if "-pooler" in url:
    sys.exit(
        "Refusing to migrate through Neon's pooled endpoint.\n"
        "PgBouncer in transaction mode cannot hold the advisory locks and session "
        "state Alembic needs. Use the direct connection string."
    )

config.set_main_option("sqlalchemy.url", url)

target_metadata = None  # RLS objects are hand-written; see the docstring.


def run_migrations_offline() -> None:
    context.configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
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

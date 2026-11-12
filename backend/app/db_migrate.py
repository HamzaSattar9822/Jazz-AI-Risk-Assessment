"""Lightweight schema patches for SQLite / Postgres without Alembic."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def ensure_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "roles" in columns:
        return
    dialect = engine.dialect.name
    logger.info("Adding users.roles column (%s)", dialect)
    with engine.begin() as conn:
        if dialect == "sqlite":
            conn.execute(text("ALTER TABLE users ADD COLUMN roles JSON DEFAULT '[]'"))
        else:
            conn.execute(text("ALTER TABLE users ADD COLUMN roles JSON DEFAULT '[]'::json"))

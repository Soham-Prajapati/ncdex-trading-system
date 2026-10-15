from collections.abc import Generator
from contextlib import contextmanager
import os

import psycopg
from datetime import datetime, timezone

from psycopg.rows import dict_row
from psycopg.types.datetime import TimestamptzLoader
try:
    from psycopg_pool import ConnectionPool
except ImportError:  # pragma: no cover
    ConnectionPool = None  # type: ignore

from .config import get_settings

# SCD2 current versions end at 'infinity'; Python's datetime cannot represent it,
# so it is loaded as the largest representable instant (rendered as ∞ by the UI).
OPEN_ENDED = datetime.max.replace(tzinfo=timezone.utc)


class InfinityTimestamptzLoader(TimestamptzLoader):
    def load(self, data):
        if bytes(data) == b"infinity":
            return OPEN_ENDED
        if bytes(data) == b"-infinity":
            return datetime.min.replace(tzinfo=timezone.utc)
        return super().load(data)


def configure(conn: psycopg.Connection) -> None:
    conn.adapters.register_loader("timestamptz", InfinityTimestamptzLoader)


def database_url() -> str:
    value = get_settings().database_url
    if not value:
        raise RuntimeError("DATABASE_URL is not configured")
    return value


_pool: ConnectionPool | None = None


def open_pool() -> ConnectionPool | None:
    """Initialize and open the database connection pool if DATABASE_URL is configured."""
    global _pool
    url = get_settings().database_url
    if not url:
        return None
    if ConnectionPool is None:
        raise RuntimeError("psycopg_pool is not installed")
    if _pool is None:
        _pool = ConnectionPool(
            url,
            min_size=2,
            max_size=10,
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
            check=ConnectionPool.check_connection,
            configure=configure,
            open=True,
        )
    elif getattr(_pool, "closed", False):
        _pool.open()
    return _pool


def close_pool() -> None:
    """Close the database connection pool on application shutdown."""
    global _pool
    if _pool is not None:
        try:
            _pool.close()
        finally:
            _pool = None


def pool() -> ConnectionPool:
    # Neon's pooler runs in transaction mode, so server-side prepared
    # statements are disabled; check() replaces connections Neon has idled out.
    global _pool
    if _pool is None or getattr(_pool, "closed", False):
        if ConnectionPool is None:
            raise RuntimeError("psycopg_pool is not installed")
        _pool = ConnectionPool(
            database_url(),
            min_size=2,
            max_size=10,
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
            check=ConnectionPool.check_connection,
            configure=configure,
            open=True,
        )
    return _pool


@contextmanager
def connection() -> Generator[psycopg.Connection, None, None]:
    with pool().connection() as conn:
        yield conn


def fetch_all(query: str, params: tuple | dict = ()) -> list[dict]:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return list(cur.fetchall())


def fetch_one(query: str, params: tuple | dict = ()) -> dict | None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()

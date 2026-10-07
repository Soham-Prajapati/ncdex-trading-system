from collections.abc import Generator
from contextlib import contextmanager
import os

import psycopg
from psycopg.rows import dict_row


def database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is not configured")
    return value


@contextmanager
def connection() -> Generator[psycopg.Connection, None, None]:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        yield conn


def fetch_all(query: str, params: tuple = ()) -> list[dict]:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return list(cur.fetchall())


def fetch_one(query: str, params: tuple = ()) -> dict | None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()


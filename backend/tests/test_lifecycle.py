"""Unit tests for Pydantic settings and database pool lifecycle management.

These tests run completely offline without connecting to a live database.
"""

import asyncio
import os
import unittest
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from app import db
from app.config import Settings, get_settings
from app.main import app


class TestSettings(unittest.TestCase):
    """Tests for Pydantic BaseSettings configuration."""

    def setUp(self):
        get_settings.cache_clear()

    def tearDown(self):
        get_settings.cache_clear()

    def test_default_settings(self):
        s = Settings(_env_file=None)
        self.assertEqual(s.database_url, "")
        self.assertIsNone(s.database_url_unpooled)
        self.assertEqual(s.api_port, 8000)
        self.assertEqual(s.api_title, "NCDEX Trading System API")
        self.assertEqual(s.api_version, "0.2.0")

    def test_valid_custom_settings(self):
        s = Settings(
            DATABASE_URL="postgresql://trader:secret@localhost:5432/ncdex",
            DATABASE_URL_UNPOOLED="postgresql://trader:secret@localhost:5432/ncdex_direct",
            API_PORT=8080,
            _env_file=None,
        )
        self.assertEqual(s.database_url, "postgresql://trader:secret@localhost:5432/ncdex")
        self.assertEqual(s.database_url_unpooled, "postgresql://trader:secret@localhost:5432/ncdex_direct")
        self.assertEqual(s.api_port, 8080)

    def test_postgres_scheme_validation(self):
        s = Settings(DATABASE_URL="postgres://trader:secret@localhost:5432/ncdex", _env_file=None)
        self.assertEqual(s.database_url, "postgres://trader:secret@localhost:5432/ncdex")

    def test_invalid_scheme_rejection(self):
        with self.assertRaises(ValidationError) as ctx:
            Settings(DATABASE_URL="mysql://root:secret@localhost:3306/ncdex", _env_file=None)
        self.assertIn("DATABASE_URL must start with postgresql:// or postgres://", str(ctx.exception))

    def test_env_var_override(self):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://envuser:pass@host/db", "API_PORT": "9000"}):
            s = Settings(_env_file=None)
            self.assertEqual(s.database_url, "postgresql://envuser:pass@host/db")
            self.assertEqual(s.api_port, 9000)

    def test_get_settings_cached(self):
        s1 = get_settings()
        s2 = get_settings()
        self.assertIs(s1, s2)


class TestDatabaseUrlHelper(unittest.TestCase):
    """Tests for database_url() validation behavior."""

    def setUp(self):
        get_settings.cache_clear()

    def tearDown(self):
        get_settings.cache_clear()

    def test_database_url_unconfigured_raises(self):
        with patch.dict(os.environ, {"DATABASE_URL": ""}, clear=True):
            get_settings.cache_clear()
            with self.assertRaises(RuntimeError) as ctx:
                db.database_url()
            self.assertIn("DATABASE_URL is not configured", str(ctx.exception))

    def test_database_url_configured_returns(self):
        url = "postgresql://trader:secret@localhost:5432/ncdex"
        with patch.dict(os.environ, {"DATABASE_URL": url}, clear=True):
            get_settings.cache_clear()
            self.assertEqual(db.database_url(), url)


class TestPoolLifecycle(unittest.TestCase):
    """Tests for open_pool() and close_pool() connection pool management."""

    def setUp(self):
        db._pool = None
        get_settings.cache_clear()

    def tearDown(self):
        db._pool = None
        get_settings.cache_clear()

    def test_open_pool_skips_when_no_database_url(self):
        """When DATABASE_URL is not set, open_pool must not attempt connection."""
        with patch.dict(os.environ, {"DATABASE_URL": ""}, clear=True):
            get_settings.cache_clear()
            res = db.open_pool()
            self.assertIsNone(res)
            self.assertIsNone(db._pool)

    def test_open_and_close_pool_with_configured_url(self):
        url = "postgresql://trader:secret@localhost:5432/ncdex"
        mock_pool_cls = MagicMock()
        mock_pool_instance = MagicMock()
        mock_pool_instance.closed = False
        mock_pool_cls.return_value = mock_pool_instance

        with patch.dict(os.environ, {"DATABASE_URL": url}, clear=True):
            get_settings.cache_clear()
            with patch.object(db, "ConnectionPool", mock_pool_cls):
                # 1. Startup: open_pool()
                pool_obj = db.open_pool()
                self.assertIs(pool_obj, mock_pool_instance)
                self.assertIs(db._pool, mock_pool_instance)
                mock_pool_cls.assert_called_once()
                call_args, call_kwargs = mock_pool_cls.call_args
                self.assertEqual(call_args[0], url)
                self.assertEqual(call_kwargs["min_size"], 2)
                self.assertEqual(call_kwargs["max_size"], 10)
                self.assertTrue(call_kwargs["open"])

                # Subsequent call reuses existing open pool
                self.assertIs(db.open_pool(), mock_pool_instance)
                self.assertEqual(mock_pool_cls.call_count, 1)

                # 2. Shutdown: close_pool()
                db.close_pool()
                mock_pool_instance.close.assert_called_once()
                self.assertIsNone(db._pool)

                # Subsequent close is safe no-op
                db.close_pool()

    def test_open_pool_reopens_if_closed(self):
        url = "postgresql://trader:secret@localhost:5432/ncdex"
        mock_pool = MagicMock()
        mock_pool.closed = True
        db._pool = mock_pool

        with patch.dict(os.environ, {"DATABASE_URL": url}, clear=True):
            get_settings.cache_clear()
            with patch.object(db, "ConnectionPool", MagicMock()):
                db.open_pool()
                mock_pool.open.assert_called_once()


class TestFastAPILifecycle(unittest.TestCase):
    """Tests for FastAPI app lifespan startup and shutdown hooks."""

    def test_lifespan_startup_and_shutdown(self):
        open_called = False
        close_called = False

        def fake_open():
            nonlocal open_called
            open_called = True

        def fake_close():
            nonlocal close_called
            close_called = True

        with patch("app.main.open_pool", side_effect=fake_open), \
             patch("app.main.close_pool", side_effect=fake_close):
            async def run_lifecycle():
                async with app.router.lifespan_context(app):
                    self.assertTrue(open_called)
                    self.assertFalse(close_called)
                self.assertTrue(close_called)

            asyncio.run(run_lifecycle())


if __name__ == "__main__":
    unittest.main()

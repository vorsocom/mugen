"""Unit tests for shared SQLAlchemy runtime configuration helpers."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from mugen.core.gateway.storage.rdbms.sqla.shared_runtime import SharedSQLAlchemyRuntime
from mugen.core.utility.rdbms_schema import (
    AGENT_RUNTIME_SCHEMA_TOKEN,
    CONTEXT_ENGINE_SCHEMA_TOKEN,
    CORE_SCHEMA_TOKEN,
)


def _make_config(
    *,
    url: str | None = "postgresql+asyncpg://user:pw@localhost:5432/db",
    pool_pre_ping: object = True,
    pool_recycle_seconds: object = 1800,
    pool_timeout_seconds: object = 30,
    pool_size: object = 10,
    max_overflow: object = 20,
    statement_timeout_ms: object = None,
) -> SimpleNamespace:
    sqlalchemy = SimpleNamespace(
        url=url,
        pool_pre_ping=pool_pre_ping,
        pool_recycle_seconds=pool_recycle_seconds,
        pool_timeout_seconds=pool_timeout_seconds,
        pool_size=pool_size,
        max_overflow=max_overflow,
        statement_timeout_ms=statement_timeout_ms,
    )
    migration_tracks = SimpleNamespace(
        core=SimpleNamespace(schema="core_runtime"),
        plugins=[],
    )
    return SimpleNamespace(
        rdbms=SimpleNamespace(
            sqlalchemy=sqlalchemy,
            migration_tracks=migration_tracks,
        )
    )


class TestSharedSQLAlchemyRuntime(unittest.IsolatedAsyncioTestCase):
    """Covers static parsing helpers and engine/sessionmaker build wiring."""

    def test_parse_helpers(self) -> None:
        self.assertTrue(SharedSQLAlchemyRuntime._resolve_bool(True, default=False))
        self.assertFalse(SharedSQLAlchemyRuntime._resolve_bool(False, default=True))
        self.assertTrue(SharedSQLAlchemyRuntime._resolve_bool(" yes ", default=False))
        self.assertFalse(SharedSQLAlchemyRuntime._resolve_bool("off", default=True))
        self.assertTrue(SharedSQLAlchemyRuntime._resolve_bool("unknown", default=True))
        self.assertFalse(SharedSQLAlchemyRuntime._resolve_bool(object(), default=False))

        self.assertEqual(
            SharedSQLAlchemyRuntime._resolve_positive_int(
                "4",
                default=1,
                field_name="field",
            ),
            4,
        )
        self.assertEqual(
            SharedSQLAlchemyRuntime._resolve_positive_int(
                None,
                default=9,
                field_name="field",
            ),
            9,
        )
        with self.assertRaisesRegex(RuntimeError, "field"):
            SharedSQLAlchemyRuntime._resolve_positive_int(
                0,
                default=9,
                field_name="field",
            )
        with self.assertRaisesRegex(RuntimeError, "field"):
            SharedSQLAlchemyRuntime._resolve_positive_int(
                "bad",
                default=7,
                field_name="field",
            )
        with self.assertRaisesRegex(RuntimeError, "field"):
            SharedSQLAlchemyRuntime._resolve_positive_int(
                True,
                default=7,
                field_name="field",
            )

        self.assertEqual(
            SharedSQLAlchemyRuntime._resolve_nonnegative_int(
                "5",
                default=1,
                field_name="field",
            ),
            5,
        )
        self.assertEqual(
            SharedSQLAlchemyRuntime._resolve_nonnegative_int(
                0,
                default=1,
                field_name="field",
            ),
            0,
        )
        self.assertEqual(
            SharedSQLAlchemyRuntime._resolve_nonnegative_int(
                None,
                default=6,
                field_name="field",
            ),
            6,
        )
        with self.assertRaisesRegex(RuntimeError, "field"):
            SharedSQLAlchemyRuntime._resolve_nonnegative_int(
                -1,
                default=6,
                field_name="field",
            )
        with self.assertRaisesRegex(RuntimeError, "field"):
            SharedSQLAlchemyRuntime._resolve_nonnegative_int(
                "bad",
                default=3,
                field_name="field",
            )
        with self.assertRaisesRegex(RuntimeError, "field"):
            SharedSQLAlchemyRuntime._resolve_nonnegative_int(
                False,
                default=3,
                field_name="field",
            )

        self.assertIsNone(SharedSQLAlchemyRuntime._resolve_statement_timeout_ms(None))
        self.assertIsNone(SharedSQLAlchemyRuntime._resolve_statement_timeout_ms(""))
        with self.assertRaisesRegex(RuntimeError, "statement_timeout_ms"):
            SharedSQLAlchemyRuntime._resolve_statement_timeout_ms("bad")
        with self.assertRaisesRegex(RuntimeError, "statement_timeout_ms"):
            SharedSQLAlchemyRuntime._resolve_statement_timeout_ms(0)
        with self.assertRaisesRegex(RuntimeError, "statement_timeout_ms"):
            SharedSQLAlchemyRuntime._resolve_statement_timeout_ms(True)
        self.assertEqual(SharedSQLAlchemyRuntime._resolve_statement_timeout_ms("2500"), 2500)

    def test_from_config_asyncpg_applies_pool_and_statement_timeout(self) -> None:
        config = _make_config(
            pool_pre_ping="false",
            pool_recycle_seconds="11",
            pool_timeout_seconds="12",
            pool_size="13",
            max_overflow="14",
            statement_timeout_ms="1500",
        )
        engine = object()
        session_maker = object()

        with (
            patch(
                "mugen.core.gateway.storage.rdbms.sqla.shared_runtime.create_async_engine",
                return_value=engine,
            ) as create_engine,
            patch(
                "mugen.core.gateway.storage.rdbms.sqla.shared_runtime.async_sessionmaker",
                return_value=session_maker,
            ) as sessionmaker_ctor,
        ):
            runtime = SharedSQLAlchemyRuntime.from_config(config)

        create_engine.assert_called_once_with(
            "postgresql+asyncpg://user:pw@localhost:5432/db",
            pool_pre_ping=False,
            pool_recycle=11,
            pool_timeout=12,
            pool_size=13,
            max_overflow=14,
            connect_args={"server_settings": {"statement_timeout": "1500"}},
            execution_options={
                "schema_translate_map": {
                    CORE_SCHEMA_TOKEN: "core_runtime",
                    CONTEXT_ENGINE_SCHEMA_TOKEN: "core_runtime",
                    AGENT_RUNTIME_SCHEMA_TOKEN: "core_runtime",
                }
            },
        )
        sessionmaker_ctor.assert_called_once_with(engine, expire_on_commit=False)
        self.assertIs(runtime.engine, engine)
        self.assertIs(runtime.session_maker, session_maker)

    def test_from_config_psycopg_uses_options_statement_timeout(self) -> None:
        config = _make_config(
            url="postgresql+psycopg://user:pw@localhost:5432/db",
            statement_timeout_ms=900,
        )
        with (
            patch(
                "mugen.core.gateway.storage.rdbms.sqla.shared_runtime.create_async_engine",
                return_value=object(),
            ) as create_engine,
            patch(
                "mugen.core.gateway.storage.rdbms.sqla.shared_runtime.async_sessionmaker",
                return_value=object(),
            ),
        ):
            SharedSQLAlchemyRuntime.from_config(config)

        self.assertEqual(
            create_engine.call_args.kwargs["execution_options"],
            {
                "schema_translate_map": {
                    CORE_SCHEMA_TOKEN: "core_runtime",
                    CONTEXT_ENGINE_SCHEMA_TOKEN: "core_runtime",
                    AGENT_RUNTIME_SCHEMA_TOKEN: "core_runtime",
                }
            },
        )
        self.assertEqual(
            create_engine.call_args.kwargs["connect_args"],
            {"options": "-c statement_timeout=900"},
        )

    def test_from_config_non_postgres_ignores_statement_timeout_connect_args(self) -> None:
        config = _make_config(
            url="sqlite+aiosqlite:///tmp/test.db",
            statement_timeout_ms=900,
        )
        with (
            patch(
                "mugen.core.gateway.storage.rdbms.sqla.shared_runtime.create_async_engine",
                return_value=object(),
            ) as create_engine,
            patch(
                "mugen.core.gateway.storage.rdbms.sqla.shared_runtime.async_sessionmaker",
                return_value=object(),
            ),
        ):
            SharedSQLAlchemyRuntime.from_config(config)

        self.assertEqual(
            create_engine.call_args.kwargs["execution_options"],
            {
                "schema_translate_map": {
                    CORE_SCHEMA_TOKEN: "core_runtime",
                    CONTEXT_ENGINE_SCHEMA_TOKEN: "core_runtime",
                    AGENT_RUNTIME_SCHEMA_TOKEN: "core_runtime",
                }
            },
        )
        self.assertNotIn("connect_args", create_engine.call_args.kwargs)

    def test_from_config_without_statement_timeout_uses_base_engine_kwargs(self) -> None:
        config = _make_config(statement_timeout_ms=None)
        with (
            patch(
                "mugen.core.gateway.storage.rdbms.sqla.shared_runtime.create_async_engine",
                return_value=object(),
            ) as create_engine,
            patch(
                "mugen.core.gateway.storage.rdbms.sqla.shared_runtime.async_sessionmaker",
                return_value=object(),
            ),
        ):
            SharedSQLAlchemyRuntime.from_config(config)

        self.assertEqual(
            create_engine.call_args.kwargs["execution_options"],
            {
                "schema_translate_map": {
                    CORE_SCHEMA_TOKEN: "core_runtime",
                    CONTEXT_ENGINE_SCHEMA_TOKEN: "core_runtime",
                    AGENT_RUNTIME_SCHEMA_TOKEN: "core_runtime",
                }
            },
        )
        self.assertNotIn("connect_args", create_engine.call_args.kwargs)

    def test_from_config_requires_url(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "requires rdbms.sqlalchemy.url"):
            SharedSQLAlchemyRuntime.from_config(_make_config(url=None))

    async def test_aclose_disposes_engine(self) -> None:
        engine = SimpleNamespace(dispose=AsyncMock())
        runtime = SharedSQLAlchemyRuntime(engine=engine, session_maker=object())

        await runtime.aclose()

        engine.dispose.assert_awaited_once_with()

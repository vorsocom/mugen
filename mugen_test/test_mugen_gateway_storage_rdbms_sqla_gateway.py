"""Unit tests for mugen.core.gateway.storage.rdbms.sqla.sqla_gateway."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import Column, Integer, MetaData, String, Table

from mugen.core.gateway.storage.rdbms.sqla import sqla_gateway
from mugen.core.gateway.storage.rdbms.sqla.shared_runtime import SharedSQLAlchemyRuntime
from mugen.core.gateway.storage.rdbms.sqla.sqla_gateway import (
    SQLAlchemyRelationalStorageGateway,
)


class _AsyncCM:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self):
        self.begin_calls = 0

    def begin(self):
        self.begin_calls += 1
        return _AsyncCM(None)


class _FakeSessionMaker:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return _AsyncCM(self._session)


class _FakeConn:
    def __init__(self):
        self.executed = []

    async def execute(self, stmt):
        self.executed.append(str(stmt))
        return None


class _FakeEngine:
    def __init__(self, conn):
        self._conn = conn

    def connect(self):
        return _AsyncCM(self._conn)


class TestMugenSQLAGateway(unittest.IsolatedAsyncioTestCase):
    """Covers gateway initialization, registration, and context managers."""

    def setUp(self) -> None:
        metadata = MetaData()
        self.widgets = Table(
            "widgets",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("name", String(64), nullable=False),
        )
        self.extras = Table(
            "extras",
            metadata,
            Column("id", Integer, primary_key=True),
        )
        self.config = SimpleNamespace()
        self.runtime = SimpleNamespace(engine="engine", session_maker="session-maker")

    def test_init_and_register_tables(self) -> None:
        with (
            patch.object(
                sqla_gateway,
                "build_table_registry_from_base",
                return_value={"widgets": self.widgets},
            ) as build_registry,
        ):
            gateway = SQLAlchemyRelationalStorageGateway(
                config=self.config,
                logging_gateway=SimpleNamespace(),
                relational_runtime=self.runtime,
            )

        build_registry.assert_called_once()
        self.assertEqual(gateway._tables["widgets"], self.widgets)  # pylint: disable=protected-access

        gateway.register_tables({"extras": self.extras})
        self.assertEqual(gateway._tables["extras"], self.extras)  # pylint: disable=protected-access

        with self.assertRaises(ValueError):
            gateway.register_tables({"widgets": self.extras})

    async def test_unit_of_work_context(self) -> None:
        with (
            patch.object(
                sqla_gateway,
                "build_table_registry_from_base",
                return_value={"widgets": self.widgets},
            ),
        ):
            gateway = SQLAlchemyRelationalStorageGateway(
                config=self.config,
                logging_gateway=SimpleNamespace(),
                relational_runtime=self.runtime,
            )

        fake_session = _FakeSession()
        gateway._session_maker = _FakeSessionMaker(fake_session)  # pylint: disable=protected-access
        gateway._tables = {"widgets": self.widgets}  # pylint: disable=protected-access

        with patch.object(
            sqla_gateway,
            "SQLAlchemyRelationalUnitOfWork",
            return_value="uow-marker",
        ) as uow_ctor:
            async with gateway.unit_of_work() as uow:
                self.assertEqual(uow, "uow-marker")
            uow_ctor.assert_called_once_with(fake_session, {"widgets": self.widgets})

        self.assertEqual(fake_session.begin_calls, 1)

    async def test_aclose_is_noop_for_shared_runtime(self) -> None:
        with patch.object(
            sqla_gateway,
            "build_table_registry_from_base",
            return_value={"widgets": self.widgets},
        ):
            gateway = SQLAlchemyRelationalStorageGateway(
                config=self.config,
                logging_gateway=SimpleNamespace(),
                relational_runtime=self.runtime,
            )
        self.assertIsNone(await gateway.aclose())

    async def test_check_readiness_runs_probe_query(self) -> None:
        with (
            patch.object(
                sqla_gateway,
                "build_table_registry_from_base",
                return_value={"widgets": self.widgets},
            ),
        ):
            gateway = SQLAlchemyRelationalStorageGateway(
                config=self.config,
                logging_gateway=SimpleNamespace(),
                relational_runtime=self.runtime,
            )

        conn = _FakeConn()
        gateway._engine = _FakeEngine(conn)  # pylint: disable=protected-access

        await gateway.check_readiness()

        self.assertEqual(conn.executed, ["SELECT 1"])


class TestSharedSQLAlchemyRuntime(unittest.TestCase):
    def test_from_config_requires_sqlalchemy_url(self) -> None:
        config = SimpleNamespace(
            rdbms=SimpleNamespace(sqlalchemy=SimpleNamespace(url="")),
        )
        with self.assertRaises(RuntimeError):
            SharedSQLAlchemyRuntime.from_config(config)

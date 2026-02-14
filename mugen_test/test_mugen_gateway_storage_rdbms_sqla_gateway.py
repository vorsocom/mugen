"""Unit tests for mugen.core.gateway.storage.rdbms.sqla.sqla_gateway."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import Column, Integer, MetaData, String, Table

from mugen.core.gateway.storage.rdbms.sqla import sqla_gateway
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
        self.config = SimpleNamespace(
            rdbms=SimpleNamespace(
                sqlalchemy=SimpleNamespace(url="sqlite+aiosqlite:///:memory:")
            )
        )

    def test_init_and_register_tables(self) -> None:
        with (
            patch.object(sqla_gateway, "create_async_engine", return_value="engine") as cae,
            patch.object(
                sqla_gateway,
                "build_table_registry_from_base",
                return_value={"widgets": self.widgets},
            ) as build_registry,
            patch.object(sqla_gateway, "async_sessionmaker", return_value="session-maker") as asm,
        ):
            gateway = SQLAlchemyRelationalStorageGateway(
                config=self.config,
                logging_gateway=SimpleNamespace(),
            )

        cae.assert_called_once_with("sqlite+aiosqlite:///:memory:")
        build_registry.assert_called_once()
        asm.assert_called_once_with("engine", expire_on_commit=False)
        self.assertEqual(gateway._tables["widgets"], self.widgets)  # pylint: disable=protected-access

        gateway.register_tables({"extras": self.extras})
        self.assertEqual(gateway._tables["extras"], self.extras)  # pylint: disable=protected-access

        with self.assertRaises(ValueError):
            gateway.register_tables({"widgets": self.extras})

    async def test_unit_of_work_and_raw_session_contexts(self) -> None:
        with (
            patch.object(sqla_gateway, "create_async_engine", return_value="engine"),
            patch.object(
                sqla_gateway,
                "build_table_registry_from_base",
                return_value={"widgets": self.widgets},
            ),
            patch.object(sqla_gateway, "async_sessionmaker", return_value="session-maker"),
        ):
            gateway = SQLAlchemyRelationalStorageGateway(
                config=self.config,
                logging_gateway=SimpleNamespace(),
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

        async with gateway.raw_session() as raw:
            self.assertIs(raw, fake_session)

        self.assertEqual(fake_session.begin_calls, 2)

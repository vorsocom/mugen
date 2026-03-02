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
    def __init__(
        self,
        *,
        columns: dict[str, set[str]] | None = None,
        constraints: dict[str, set[str]] | None = None,
        indexes: dict[str, set[str]] | None = None,
    ):
        self.executed: list[str] = []
        self._columns = columns or {}
        self._constraints = constraints or {}
        self._indexes = indexes or {}

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed.append(sql)
        params = params or {}
        table_name = params.get("table_name")
        if "information_schema.columns" in sql:
            return [
                SimpleNamespace(column_name=name)
                for name in sorted(self._columns.get(table_name, set()))
            ]
        if "information_schema.table_constraints" in sql:
            return [
                SimpleNamespace(constraint_name=name)
                for name in sorted(self._constraints.get(table_name, set()))
            ]
        if "FROM pg_indexes" in sql:
            return [
                SimpleNamespace(indexname=name)
                for name in sorted(self._indexes.get(table_name, set()))
            ]
        return []


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
        self.config = SimpleNamespace(mugen=SimpleNamespace(platforms=[]))
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

        required = gateway._required_schema_checks()  # pylint: disable=protected-access
        columns = {name: set(meta["columns"]) for name, meta in required.items()}
        constraints = {name: set(meta["constraints"]) for name, meta in required.items()}
        indexes = {name: set(meta["indexes"]) for name, meta in required.items()}
        conn = _FakeConn(columns=columns, constraints=constraints, indexes=indexes)
        gateway._engine = _FakeEngine(conn)  # pylint: disable=protected-access

        await gateway.check_readiness()

        self.assertIn("SELECT 1", conn.executed[0])

    async def test_check_readiness_raises_for_missing_schema_elements(self) -> None:
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

        required = gateway._required_schema_checks()  # pylint: disable=protected-access
        columns = {name: set(meta["columns"]) for name, meta in required.items()}
        constraints = {name: set(meta["constraints"]) for name, meta in required.items()}
        indexes = {name: set(meta["indexes"]) for name, meta in required.items()}
        table_name = next(iter(required.keys()))

        columns[table_name] = set()
        gateway._engine = _FakeEngine(  # pylint: disable=protected-access
            _FakeConn(columns=columns, constraints=constraints, indexes=indexes)
        )
        with self.assertRaisesRegex(RuntimeError, "missing column"):
            await gateway.check_readiness()

        columns[table_name] = set(required[table_name]["columns"])
        constraints[table_name] = set()
        gateway._engine = _FakeEngine(  # pylint: disable=protected-access
            _FakeConn(columns=columns, constraints=constraints, indexes=indexes)
        )
        with self.assertRaisesRegex(RuntimeError, "missing constraint"):
            await gateway.check_readiness()

        constraints[table_name] = set(required[table_name]["constraints"])
        indexes[table_name] = set()
        gateway._engine = _FakeEngine(  # pylint: disable=protected-access
            _FakeConn(columns=columns, constraints=constraints, indexes=indexes)
        )
        with self.assertRaisesRegex(RuntimeError, "missing index"):
            await gateway.check_readiness()

    def test_required_schema_checks_include_web_tables_only_when_web_enabled(self) -> None:
        with patch.object(
            sqla_gateway,
            "build_table_registry_from_base",
            return_value={"widgets": self.widgets},
        ):
            gateway = SQLAlchemyRelationalStorageGateway(
                config=SimpleNamespace(mugen=SimpleNamespace(platforms=[])),
                logging_gateway=SimpleNamespace(),
                relational_runtime=self.runtime,
            )
        checks = gateway._required_schema_checks()  # pylint: disable=protected-access
        self.assertIn("core_keyval_entry", checks)
        self.assertNotIn("web_queue_job", checks)

        gateway._config = SimpleNamespace(mugen=SimpleNamespace(platforms=["web"]))  # pylint: disable=protected-access
        checks = gateway._required_schema_checks()  # pylint: disable=protected-access
        self.assertIn("web_queue_job", checks)
        self.assertIn("web_conversation_state", checks)
        self.assertIn("web_conversation_event", checks)
        self.assertIn("web_media_token", checks)


class TestSharedSQLAlchemyRuntime(unittest.TestCase):
    def test_from_config_requires_sqlalchemy_url(self) -> None:
        config = SimpleNamespace(
            rdbms=SimpleNamespace(sqlalchemy=SimpleNamespace(url="")),
        )
        with self.assertRaises(RuntimeError):
            SharedSQLAlchemyRuntime.from_config(config)

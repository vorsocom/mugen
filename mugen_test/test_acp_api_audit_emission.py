"""Focused tests for ACP audit emission helper."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
import uuid
from unittest.mock import Mock, patch

from quart import Quart


def _bootstrap_namespace_packages() -> None:
    root = Path(__file__).resolve().parents[1] / "mugen"

    if "mugen" not in sys.modules:
        mugen_pkg = ModuleType("mugen")
        mugen_pkg.__path__ = [str(root)]
        sys.modules["mugen"] = mugen_pkg

    if "mugen.core" not in sys.modules:
        core_pkg = ModuleType("mugen.core")
        core_pkg.__path__ = [str(root / "core")]
        sys.modules["mugen.core"] = core_pkg
        setattr(sys.modules["mugen"], "core", core_pkg)

    if "mugen.core.di" not in sys.modules:
        di_mod = ModuleType("mugen.core.di")
        di_mod.container = SimpleNamespace(
            config=SimpleNamespace(),
            logging_gateway=SimpleNamespace(debug=lambda *_: None),
        )
        sys.modules["mugen.core.di"] = di_mod
        setattr(sys.modules["mugen.core"], "di", di_mod)


_bootstrap_namespace_packages()

from mugen.core.plugin.acp.api import audit as audit_mod  # noqa: E402  pylint: disable=wrong-import-position
from mugen.core.plugin.acp.api.audit import emit_audit_event  # noqa: E402  pylint: disable=wrong-import-position


@dataclass
class _DummyEntity:
    id: uuid.UUID
    name: str
    happened_at: datetime


class _FakeAuditService:
    def __init__(self) -> None:
        self.records: list[dict] = []

    async def create(self, values: dict):
        self.records.append(values)
        return values


class _FailingAuditService:
    async def create(self, _values: dict):
        raise RuntimeError("write failed")


class _FakeRegistry:
    def __init__(self, svc: _FakeAuditService) -> None:
        self._svc = svc

    def get_resource(self, entity_set: str):
        if entity_set != "AuditEvents":
            raise KeyError(entity_set)
        return SimpleNamespace(service_key="audit_svc")

    def get_edm_service(self, key: str):
        if key != "audit_svc":
            raise KeyError(key)
        return self._svc


class _MissingAuditRegistry:
    def get_resource(self, entity_set: str):
        raise KeyError(entity_set)


class TestACPAuditEmission(unittest.IsolatedAsyncioTestCase):
    """Tests for audit event payload generation."""

    def test_helper_functions_and_json_serialization(self) -> None:
        fake_config = SimpleNamespace()
        fake_logger = Mock()
        with patch.object(
            audit_mod.di,
            "container",
            new=SimpleNamespace(config=fake_config, logging_gateway=fake_logger),
        ):
            self.assertIs(audit_mod._config_provider(), fake_config)  # pylint: disable=protected-access
            self.assertIs(audit_mod._logger_provider(), fake_logger)  # pylint: disable=protected-access

        class _Mode(Enum):
            READY = "ready"

        payload = {
            "uuid": uuid.uuid4(),
            "naive_dt": datetime(2026, 2, 11, 10, 0, 0),
            "enum": _Mode.READY,
            "dataclass": _DummyEntity(
                id=uuid.uuid4(),
                name="test",
                happened_at=datetime(2026, 2, 11, tzinfo=timezone.utc),
            ),
            "items": ("a", "b"),
            "set_items": {"x", "y"},
            "obj": object(),
        }
        json_safe_payload = audit_mod._json_safe(payload)  # pylint: disable=protected-access
        self.assertIsInstance(json_safe_payload["uuid"], str)
        self.assertTrue(json_safe_payload["naive_dt"].endswith("+00:00"))
        self.assertEqual(json_safe_payload["enum"], "ready")
        self.assertEqual(json_safe_payload["dataclass"]["name"], "test")
        self.assertEqual(json_safe_payload["items"], ["a", "b"])
        self.assertEqual(sorted(json_safe_payload["set_items"]), ["x", "y"])
        self.assertIsInstance(json_safe_payload["obj"], str)

        self.assertIsNone(audit_mod._json_safe(None))  # pylint: disable=protected-access
        self.assertEqual(audit_mod._json_safe(3), 3)  # pylint: disable=protected-access
        self.assertEqual(audit_mod._json_safe(True), True)  # pylint: disable=protected-access

        self.assertIsNone(audit_mod._parse_positive_int(None))  # pylint: disable=protected-access
        self.assertIsNone(audit_mod._parse_positive_int("bad"))  # pylint: disable=protected-access
        self.assertIsNone(audit_mod._parse_positive_int(0))  # pylint: disable=protected-access
        self.assertIsNone(audit_mod._parse_positive_int(-5))  # pylint: disable=protected-access
        self.assertEqual(audit_mod._parse_positive_int("9"), 9)  # pylint: disable=protected-access

        defaults = audit_mod._resolve_snapshot_policy(SimpleNamespace())  # pylint: disable=protected-access
        self.assertEqual(defaults, (False, False, None, None))

    async def test_request_id_resolution_paths(self) -> None:
        app = Quart("audit-request-id-paths")

        req, corr = audit_mod._resolve_request_ids("r1", "c1")  # pylint: disable=protected-access
        self.assertEqual((req, corr), ("r1", "c1"))

        req_no_ctx, corr_no_ctx = audit_mod._resolve_request_ids(None, None)  # pylint: disable=protected-access
        self.assertEqual((req_no_ctx, corr_no_ctx), (None, None))

        async with app.test_request_context(
            "/api/core/acp/v1/Users",
            headers={"X-Request-Id": "req-1", "X-Correlation-Id": "corr-1"},
        ):
            req_hdr, corr_hdr = audit_mod._resolve_request_ids(None, None)  # pylint: disable=protected-access
            self.assertEqual((req_hdr, corr_hdr), ("req-1", "corr-1"))

        async with app.test_request_context(
            "/api/core/acp/v1/Users",
            headers={"X-Request-Id": "req-2", "X-Trace-Id": "trace-2"},
        ):
            req_hdr, corr_hdr = audit_mod._resolve_request_ids(None, None)  # pylint: disable=protected-access
            self.assertEqual((req_hdr, corr_hdr), ("req-2", "trace-2"))

        async with app.test_request_context(
            "/api/core/acp/v1/Users",
            headers={"X-Request-Id": "req-3"},
        ):
            req_hdr, corr_hdr = audit_mod._resolve_request_ids(None, None)  # pylint: disable=protected-access
            self.assertEqual((req_hdr, corr_hdr), ("req-3", "req-3"))

        async with app.test_request_context(
            "/api/core/acp/v1/Users",
            headers={"X-Correlation-Id": "corr-4"},
        ):
            req_hdr, corr_hdr = audit_mod._resolve_request_ids(  # pylint: disable=protected-access
                "req-4",
                None,
            )
            self.assertEqual((req_hdr, corr_hdr), ("req-4", "corr-4"))

        async with app.test_request_context(
            "/api/core/acp/v1/Users",
            headers={"X-Request-Id": "req-5"},
        ):
            req_hdr, corr_hdr = audit_mod._resolve_request_ids(  # pylint: disable=protected-access
                None,
                "corr-5",
            )
            self.assertEqual((req_hdr, corr_hdr), ("req-5", "corr-5"))

    async def test_emit_honors_snapshot_and_retention_policy(self):
        audit_svc = _FakeAuditService()
        registry = _FakeRegistry(audit_svc)

        actor_id = uuid.uuid4()
        entity_id = uuid.uuid4()

        before = _DummyEntity(
            id=entity_id,
            name="before",
            happened_at=datetime(2026, 2, 11, tzinfo=timezone.utc),
        )
        after = {
            "id": entity_id,
            "name": "after",
        }

        config = SimpleNamespace(
            audit=SimpleNamespace(
                include_before_snapshot=True,
                include_after_snapshot=False,
                retention_days=30,
                redaction_days=7,
            )
        )

        await emit_audit_event(
            registry=registry,
            entity_set="Users",
            entity="User",
            entity_id=entity_id,
            operation="update",
            outcome="success",
            source_plugin="com.vorsocomputing.mugen.acp",
            actor_id=actor_id,
            changed_fields=["display_name", "display_name", "email"],
            before=before,
            after=after,
            request_id="req-1",
            correlation_id="corr-1",
            config_provider=lambda: config,
            logger_provider=lambda: SimpleNamespace(debug=lambda *_: None),
        )

        self.assertEqual(len(audit_svc.records), 1)
        record = audit_svc.records[0]

        self.assertEqual(record["entity_set"], "Users")
        self.assertEqual(record["entity"], "User")
        self.assertEqual(record["operation"], "update")
        self.assertEqual(record["outcome"], "success")
        self.assertEqual(record["actor_id"], actor_id)
        self.assertEqual(record["request_id"], "req-1")
        self.assertEqual(record["correlation_id"], "corr-1")
        self.assertEqual(record["changed_fields"], ["display_name", "email"])
        self.assertIsNotNone(record["before_snapshot"])
        self.assertIsNone(record["after_snapshot"])
        self.assertIsNotNone(record["retention_until"])
        self.assertIsNotNone(record["redaction_due_at"])

    async def test_emit_noops_when_audit_resource_not_registered(self):
        registry = _MissingAuditRegistry()

        await emit_audit_event(
            registry=registry,
            entity_set="Users",
            entity="User",
            operation="create",
            outcome="success",
            source_plugin="com.vorsocomputing.mugen.acp",
            request_id="req-1",
            correlation_id="corr-1",
            logger_provider=lambda: SimpleNamespace(debug=lambda *_: None),
        )

    async def test_emit_logs_when_audit_service_create_fails(self):
        registry = _FakeRegistry(_FailingAuditService())
        logger = Mock()

        await emit_audit_event(
            registry=registry,
            entity_set="Users",
            entity="User",
            operation="create",
            outcome="error",
            source_plugin="com.vorsocomputing.mugen.acp",
            request_id="req-1",
            correlation_id="corr-1",
            logger_provider=lambda: logger,
            config_provider=lambda: SimpleNamespace(),
        )

        logger.debug.assert_called_once()

    async def test_emit_fail_closed_raises_on_write_error(self):
        registry = _FakeRegistry(_FailingAuditService())

        with self.assertRaises(RuntimeError):
            await emit_audit_event(
                registry=registry,
                entity_set="Users",
                entity="User",
                operation="create",
                outcome="error",
                source_plugin="com.vorsocomputing.mugen.acp",
                request_id="req-1",
                correlation_id="corr-1",
                logger_provider=lambda: SimpleNamespace(debug=lambda *_: None),
                config_provider=lambda: SimpleNamespace(
                    audit=SimpleNamespace(
                        emit=SimpleNamespace(
                            fail_closed=True,
                        )
                    )
                ),
            )

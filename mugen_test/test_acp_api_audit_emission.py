"""Focused tests for ACP audit emission helper."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
import uuid


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

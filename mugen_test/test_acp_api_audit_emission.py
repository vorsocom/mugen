"""Focused tests for ACP audit emission helper."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import logging
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

from mugen.core.plugin.acp.api import (
    audit as audit_mod,
)  # noqa: E402  pylint: disable=wrong-import-position

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.plugin.acp.api.audit import (
    emit_audit_event,
    emit_biz_trace_event,
)


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


class _GenericCaptureService:
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


class _MultiRegistry:
    def __init__(self, services: dict[str, object]) -> None:
        self._services = services

    def get_resource(self, entity_set: str):
        if entity_set not in self._services:
            raise KeyError(entity_set)
        return SimpleNamespace(service_key=entity_set)

    def get_edm_service(self, key: str):
        return self._services[key]


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
            self.assertIs(
                audit_mod._config_provider(), fake_config
            )  # pylint: disable=protected-access
            self.assertIs(
                audit_mod._logger_provider(), fake_logger
            )  # pylint: disable=protected-access

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
        json_safe_payload = audit_mod._json_safe(
            payload
        )  # pylint: disable=protected-access
        self.assertIsInstance(json_safe_payload["uuid"], str)
        self.assertTrue(json_safe_payload["naive_dt"].endswith("+00:00"))
        self.assertEqual(json_safe_payload["enum"], "ready")
        self.assertEqual(json_safe_payload["dataclass"]["name"], "test")
        self.assertEqual(json_safe_payload["items"], ["a", "b"])
        self.assertEqual(sorted(json_safe_payload["set_items"]), ["x", "y"])
        self.assertIsInstance(json_safe_payload["obj"], str)

        self.assertIsNone(
            audit_mod._json_safe(None)
        )  # pylint: disable=protected-access
        self.assertEqual(audit_mod._json_safe(3), 3)  # pylint: disable=protected-access
        self.assertEqual(
            audit_mod._json_safe(True), True
        )  # pylint: disable=protected-access

        self.assertIsNone(
            audit_mod._parse_positive_int(None)
        )  # pylint: disable=protected-access
        self.assertIsNone(
            audit_mod._parse_positive_int("bad")
        )  # pylint: disable=protected-access
        self.assertIsNone(
            audit_mod._parse_positive_int(0)
        )  # pylint: disable=protected-access
        self.assertIsNone(
            audit_mod._parse_positive_int(-5)
        )  # pylint: disable=protected-access
        self.assertEqual(
            audit_mod._parse_positive_int("9"), 9
        )  # pylint: disable=protected-access

        defaults = audit_mod._resolve_snapshot_policy(
            SimpleNamespace()
        )  # pylint: disable=protected-access
        self.assertEqual(defaults, (False, False, None, None))

    def test_helper_providers_fallback_when_container_access_fails(self) -> None:
        class _FailingContainer:  # pylint: disable=too-few-public-methods
            @property
            def config(self):
                raise RuntimeError("config unavailable")

            @property
            def logging_gateway(self):
                raise RuntimeError("logger unavailable")

        with patch.object(audit_mod.di, "container", new=_FailingContainer()):
            fallback_config = audit_mod._config_provider()  # pylint: disable=protected-access
            fallback_logger = audit_mod._logger_provider()  # pylint: disable=protected-access

        self.assertIsInstance(fallback_config, SimpleNamespace)
        self.assertIs(fallback_logger, logging.getLogger())

        with patch.object(
            audit_mod.di,
            "container",
            new=SimpleNamespace(config=SimpleNamespace(), logging_gateway=None),
        ):
            self.assertIs(
                audit_mod._logger_provider(),  # pylint: disable=protected-access
                logging.getLogger(),
            )

    async def test_request_id_resolution_paths(self) -> None:
        app = Quart("audit-request-id-paths")

        req, corr = audit_mod._resolve_request_ids(
            "r1", "c1"
        )  # pylint: disable=protected-access
        self.assertEqual((req, corr), ("r1", "c1"))

        req_no_ctx, corr_no_ctx = audit_mod._resolve_request_ids(
            None, None
        )  # pylint: disable=protected-access
        self.assertEqual((req_no_ctx, corr_no_ctx), (None, None))

        async with app.test_request_context(
            "/api/core/acp/v1/Users",
            headers={"X-Request-Id": "req-1", "X-Correlation-Id": "corr-1"},
        ):
            req_hdr, corr_hdr = audit_mod._resolve_request_ids(
                None, None
            )  # pylint: disable=protected-access
            self.assertEqual((req_hdr, corr_hdr), ("req-1", "corr-1"))

        async with app.test_request_context(
            "/api/core/acp/v1/Users",
            headers={"X-Request-Id": "req-2", "X-Trace-Id": "trace-2"},
        ):
            req_hdr, corr_hdr = audit_mod._resolve_request_ids(
                None, None
            )  # pylint: disable=protected-access
            self.assertEqual((req_hdr, corr_hdr), ("req-2", "trace-2"))

        async with app.test_request_context(
            "/api/core/acp/v1/Users",
            headers={"X-Request-Id": "req-3"},
        ):
            req_hdr, corr_hdr = audit_mod._resolve_request_ids(
                None, None
            )  # pylint: disable=protected-access
            self.assertEqual((req_hdr, corr_hdr), ("req-3", "req-3"))

        async with app.test_request_context(
            "/api/core/acp/v1/Users",
            headers={"X-Correlation-Id": "corr-4"},
        ):
            req_hdr, corr_hdr = (
                audit_mod._resolve_request_ids(  # pylint: disable=protected-access
                    "req-4",
                    None,
                )
            )
            self.assertEqual((req_hdr, corr_hdr), ("req-4", "corr-4"))

        async with app.test_request_context(
            "/api/core/acp/v1/Users",
            headers={"X-Request-Id": "req-5"},
        ):
            req_hdr, corr_hdr = (
                audit_mod._resolve_request_ids(  # pylint: disable=protected-access
                    None,
                    "corr-5",
                )
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

    async def test_traceparent_parsing_and_correlation_link_emission(self):
        audit_svc = _GenericCaptureService()
        corr_svc = _GenericCaptureService()
        registry = _MultiRegistry(
            services={
                "AuditEvents": audit_svc,
                "AuditCorrelationLinks": corr_svc,
            }
        )
        app = Quart("audit-traceparent")
        traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

        async with app.test_request_context(
            "/api/core/acp/v1/Users",
            headers={
                "traceparent": traceparent,
                "X-Request-Id": "req-1",
            },
        ):
            await emit_audit_event(
                registry=registry,
                entity_set="Users",
                entity="User",
                entity_id=uuid.uuid4(),
                operation="create",
                outcome="success",
                source_plugin="com.vorsocomputing.mugen.acp",
                request_id=None,
                correlation_id=None,
                logger_provider=lambda: SimpleNamespace(debug=lambda *_: None),
                config_provider=lambda: SimpleNamespace(),
            )

        self.assertEqual(len(audit_svc.records), 1)
        self.assertEqual(len(corr_svc.records), 1)
        self.assertEqual(
            corr_svc.records[0]["trace_id"],
            "4bf92f3577b34da6a3ce929d0e0e4736",
        )

        parsed = audit_mod._parse_traceparent(
            traceparent
        )  # pylint: disable=protected-access
        self.assertEqual(
            parsed,
            ("4bf92f3577b34da6a3ce929d0e0e4736", "00f067aa0ba902b7"),
        )
        self.assertEqual(
            audit_mod._parse_traceparent("bad"),  # pylint: disable=protected-access
            (None, None),
        )

    async def test_emit_biz_trace_event_respects_redaction_and_truncation(self):
        biz_svc = _GenericCaptureService()
        registry = _MultiRegistry(
            services={
                "AuditBizTraceEvents": biz_svc,
            }
        )
        redaction_config = SimpleNamespace(
            audit=SimpleNamespace(
                biz_trace=SimpleNamespace(
                    enabled=True,
                    max_detail_bytes=1024,
                    redacted_keys=["password"],
                )
            )
        )
        truncation_config = SimpleNamespace(
            audit=SimpleNamespace(
                biz_trace=SimpleNamespace(
                    enabled=True,
                    max_detail_bytes=40,
                    redacted_keys=["password"],
                )
            )
        )
        app = Quart("audit-biz-trace")

        async with app.test_request_context(
            "/api/core/acp/v1/Users",
            headers={"X-Request-Id": "req-1"},
        ):
            await emit_biz_trace_event(
                registry=registry,
                stage="finish",
                source_plugin="com.vorsocomputing.mugen.acp",
                entity_set="Users",
                action_name="provision",
                details={
                    "password": "secret",
                    "nested": {"password": "secret-2"},
                },
                config_provider=lambda: redaction_config,
                logger_provider=lambda: SimpleNamespace(debug=lambda *_: None),
            )
            await emit_biz_trace_event(
                registry=registry,
                stage="finish",
                source_plugin="com.vorsocomputing.mugen.acp",
                entity_set="Users",
                action_name="provision",
                details={
                    "text": "x" * 200,
                },
                config_provider=lambda: truncation_config,
                logger_provider=lambda: SimpleNamespace(debug=lambda *_: None),
            )

        self.assertEqual(len(biz_svc.records), 2)

        redacted_record = biz_svc.records[0]
        self.assertEqual(redacted_record["stage"], "finish")
        self.assertEqual(redacted_record["details_json"]["password"], "***REDACTED***")
        self.assertEqual(
            redacted_record["details_json"]["nested"]["password"],
            "***REDACTED***",
        )

        truncated_record = biz_svc.records[1]
        self.assertTrue(truncated_record["trace_id"])
        self.assertTrue(truncated_record["details_json"]["truncated"])

    async def test_trace_and_policy_helper_edge_paths(self) -> None:
        app = Quart("audit-helper-edges")
        self.assertEqual(
            audit_mod._parse_traceparent(  # pylint: disable=protected-access
                "00-zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz-00f067aa0ba902b7-01"
            ),
            (None, None),
        )
        self.assertEqual(
            audit_mod._parse_traceparent(  # pylint: disable=protected-access
                "00-4bf92f3577b34da6a3ce929d0e0e4736-abc-01"
            ),
            (None, None),
        )

        trace_id, span_id, parent_span_id = (
            audit_mod._resolve_trace_context(  # pylint: disable=protected-access
                request_id="req-1",
                correlation_id="corr-1",
                trace_id=None,
            )
        )
        self.assertEqual(trace_id, "corr-1")
        self.assertIsNone(span_id)
        self.assertIsNone(parent_span_id)

        trace_id, _, _ = (
            audit_mod._resolve_trace_context(  # pylint: disable=protected-access
                request_id="req-1",
                correlation_id="corr-1",
                trace_id="explicit",
            )
        )
        self.assertEqual(trace_id, "explicit")

        async with app.test_request_context(
            "/api/core/acp/v1/Users",
            headers={
                "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
            },
        ):
            trace_id, span_id, _ = (
                audit_mod._resolve_trace_context(  # pylint: disable=protected-access
                    request_id="req-1",
                    correlation_id="corr-1",
                    trace_id="explicit-trace",
                )
            )
        self.assertEqual(trace_id, "explicit-trace")
        self.assertEqual(span_id, "00f067aa0ba902b7")

        enabled, max_detail_bytes, redacted_keys = (
            audit_mod._resolve_biz_trace_policy(  # pylint: disable=protected-access
                SimpleNamespace(
                    audit=SimpleNamespace(
                        biz_trace=SimpleNamespace(
                            enabled=True,
                            max_detail_bytes=None,
                            redacted_keys=["", "password"],
                        )
                    )
                )
            )
        )
        self.assertEqual(enabled, True)
        self.assertGreater(max_detail_bytes, 0)
        self.assertEqual(redacted_keys, {"password"})

        _, _, redacted_keys = (
            audit_mod._resolve_biz_trace_policy(  # pylint: disable=protected-access
                SimpleNamespace(
                    audit=SimpleNamespace(
                        biz_trace=SimpleNamespace(
                            enabled=True,
                            max_detail_bytes=32,
                            redacted_keys="not-a-list",
                        )
                    )
                )
            )
        )
        self.assertEqual(redacted_keys, set())

        redacted = audit_mod._redact_detail_keys(  # pylint: disable=protected-access
            {
                "list": [{"password": "s"}],
                "tuple": ({"password": "s2"},),
                "set": {"a"},
            },
            {"password"},
        )
        self.assertEqual(redacted["list"][0]["password"], "***REDACTED***")
        self.assertEqual(redacted["tuple"][0]["password"], "***REDACTED***")
        self.assertEqual(redacted["set"], {"a"})

        raw_uuid = uuid.uuid4()
        self.assertEqual(
            audit_mod._coerce_optional_uuid(
                raw_uuid
            ),  # pylint: disable=protected-access
            raw_uuid,
        )
        self.assertIsNone(
            audit_mod._coerce_optional_uuid(
                "bad-uuid"
            )  # pylint: disable=protected-access
        )

    async def test_emit_correlation_and_biz_trace_error_paths(self) -> None:
        logger = Mock()
        failing_corr_service = _FailingAuditService()
        registry = _MultiRegistry(
            services={
                "AuditEvents": _GenericCaptureService(),
                "AuditCorrelationLinks": failing_corr_service,
            }
        )

        await emit_audit_event(
            registry=registry,
            entity_set="Users",
            entity="User",
            operation="create",
            outcome="success",
            source_plugin="com.vorsocomputing.mugen.acp",
            meta={},
            request_id="",
            correlation_id="",
            trace_id="",
            logger_provider=lambda: logger,
            config_provider=lambda: SimpleNamespace(),
        )
        logger.debug.assert_called()

        missing_registry = _MultiRegistry(services={})
        await emit_biz_trace_event(
            registry=missing_registry,
            stage="start",
            source_plugin="com.vorsocomputing.mugen.acp",
            entity_set="Users",
            action_name="provision",
            config_provider=lambda: SimpleNamespace(
                audit=SimpleNamespace(
                    biz_trace=SimpleNamespace(
                        enabled=True,
                        max_detail_bytes=64,
                        redacted_keys=[],
                    )
                )
            ),
            logger_provider=lambda: SimpleNamespace(debug=lambda *_: None),
        )

        biz_logger = Mock()
        await emit_biz_trace_event(
            registry=_MultiRegistry(
                services={"AuditBizTraceEvents": _FailingAuditService()}
            ),
            stage="finish",
            source_plugin="com.vorsocomputing.mugen.acp",
            entity_set="Users",
            action_name="provision",
            span_id="span-1",
            parent_span_id="parent-1",
            config_provider=lambda: SimpleNamespace(
                audit=SimpleNamespace(
                    biz_trace=SimpleNamespace(
                        enabled=True,
                        max_detail_bytes=128,
                        redacted_keys=[],
                    ),
                    emit=SimpleNamespace(fail_closed=False),
                )
            ),
            logger_provider=lambda: biz_logger,
        )
        biz_logger.debug.assert_called()

        with self.assertRaises(RuntimeError):
            await emit_biz_trace_event(
                registry=_MultiRegistry(
                    services={"AuditBizTraceEvents": _FailingAuditService()}
                ),
                stage="finish",
                source_plugin="com.vorsocomputing.mugen.acp",
                entity_set="Users",
                action_name="provision",
                config_provider=lambda: SimpleNamespace(
                    audit=SimpleNamespace(
                        biz_trace=SimpleNamespace(
                            enabled=True,
                            max_detail_bytes=128,
                            redacted_keys=[],
                        ),
                        emit=SimpleNamespace(fail_closed=True),
                    )
                ),
                logger_provider=lambda: SimpleNamespace(debug=lambda *_: None),
            )

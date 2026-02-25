"""Tests for audit correlation and business-trace services."""

from pathlib import Path
from types import ModuleType, SimpleNamespace
from datetime import datetime, timezone
import sys
import unittest
import uuid
from unittest.mock import AsyncMock

from werkzeug.exceptions import HTTPException


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


_bootstrap_namespace_packages()

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.plugin.audit.service.audit_biz_trace_event import (
    AuditBizTraceEventService,
)
from mugen.core.plugin.audit.service.audit_correlation_link import (
    AuditCorrelationLinkService,
)


class TestAuditServiceCorrelationAndBizTrace(unittest.IsolatedAsyncioTestCase):
    """Covers action payloads and graph/timeline projections."""

    async def test_correlation_resolve_trace_builds_graph(self) -> None:
        child_id = uuid.uuid4()
        parent_id = uuid.uuid4()

        service = AuditCorrelationLinkService.__new__(AuditCorrelationLinkService)
        service.list = AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=uuid.uuid4(),
                    tenant_id=uuid.uuid4(),
                    trace_id="trace-1",
                    correlation_id="corr-1",
                    request_id="req-1",
                    source_plugin="com.vorsocomputing.mugen.acp",
                    entity_set="Users",
                    entity_id=child_id,
                    operation="create",
                    action_name=None,
                    parent_entity_set="Tenants",
                    parent_entity_id=parent_id,
                    occurred_at=None,
                    attributes=None,
                )
            ]
        )

        payload, status = await service.entity_set_action_resolve_trace(
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(
                tenant_id=None,
                trace_id="trace-1",
                correlation_id=None,
                request_id=None,
                max_rows=100,
            ),
        )

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["Links"]), 1)
        self.assertEqual(len(payload["Graph"]["Nodes"]), 2)
        self.assertEqual(len(payload["Graph"]["Edges"]), 1)

    async def test_correlation_resolve_trace_requires_reference(self) -> None:
        service = AuditCorrelationLinkService.__new__(AuditCorrelationLinkService)
        service.list = AsyncMock(return_value=[])

        with self.assertRaises(HTTPException) as error:
            await service.entity_set_action_resolve_trace(
                auth_user_id=uuid.uuid4(),
                data=SimpleNamespace(
                    tenant_id=None,
                    trace_id=None,
                    correlation_id=None,
                    request_id=None,
                    max_rows=100,
                ),
            )
        self.assertEqual(error.exception.code, 400)

    async def test_biz_trace_inspect_timeline(self) -> None:
        service = AuditBizTraceEventService.__new__(AuditBizTraceEventService)
        service.list = AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=uuid.uuid4(),
                    tenant_id=uuid.uuid4(),
                    trace_id="trace-1",
                    span_id="span-1",
                    parent_span_id=None,
                    correlation_id="corr-1",
                    request_id="req-1",
                    source_plugin="com.vorsocomputing.mugen.acp",
                    entity_set="Users",
                    action_name="provision",
                    stage="finish",
                    status_code=200,
                    duration_ms=12,
                    details_json={"ok": True},
                    occurred_at=None,
                )
            ]
        )

        payload, status = await service.entity_set_action_inspect_trace(
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(
                tenant_id=None,
                trace_id="trace-1",
                correlation_id=None,
                request_id=None,
                stage=None,
                max_rows=50,
            ),
        )

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["Events"]), 1)
        self.assertEqual(payload["Events"][0]["Stage"], "finish")

    async def test_biz_trace_inspect_requires_reference(self) -> None:
        service = AuditBizTraceEventService.__new__(AuditBizTraceEventService)
        service.list = AsyncMock(return_value=[])

        with self.assertRaises(HTTPException) as error:
            await service.entity_set_action_inspect_trace(
                auth_user_id=uuid.uuid4(),
                data=SimpleNamespace(
                    tenant_id=None,
                    trace_id=None,
                    correlation_id=None,
                    request_id=None,
                    stage=None,
                    max_rows=50,
                ),
            )
        self.assertEqual(error.exception.code, 400)

    async def test_correlation_service_helpers_and_tenant_action(self) -> None:
        service = AuditCorrelationLinkService(
            table="audit_correlation_link",
            rsg=SimpleNamespace(),
        )
        self.assertEqual(
            service._normalize_max_rows("bad"), 500
        )  # pylint: disable=protected-access
        self.assertEqual(
            service._normalize_max_rows(0), 500
        )  # pylint: disable=protected-access
        self.assertEqual(
            service._normalize_max_rows(6_000), 5_000
        )  # pylint: disable=protected-access
        self.assertIsNone(service._uuid_text(None))  # pylint: disable=protected-access
        self.assertTrue(
            service._datetime_text(datetime(2026, 1, 1)).endswith(
                "+00:00"
            )  # pylint: disable=protected-access
        )
        self.assertTrue(
            service._datetime_text(datetime(2026, 1, 1, tzinfo=timezone.utc)).endswith(
                "+00:00"
            )  # pylint: disable=protected-access
        )

        tenant_id = uuid.uuid4()
        service.list = AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    trace_id="trace-1",
                    correlation_id="corr-1",
                    request_id="req-1",
                    source_plugin="com.vorsocomputing.mugen.acp",
                    entity_set="Users",
                    entity_id=uuid.uuid4(),
                    operation="update",
                    action_name="promote",
                    parent_entity_set=None,
                    parent_entity_id=None,
                    occurred_at=datetime(2026, 1, 1),
                    attributes={"k": "v"},
                )
            ]
        )

        payload, status = await service.action_resolve_trace(
            tenant_id=tenant_id,
            where={},
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(
                trace_id=None,
                correlation_id="corr-1",
                request_id="req-1",
                max_rows=0,
            ),
        )

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["Links"]), 1)
        self.assertEqual(len(payload["Graph"]["Nodes"]), 1)
        filter_group = service.list.await_args.kwargs["filter_groups"][0]
        self.assertEqual(filter_group.where["tenant_id"], tenant_id)
        self.assertEqual(filter_group.where["correlation_id"], "corr-1")
        self.assertEqual(filter_group.where["request_id"], "req-1")

    async def test_biz_trace_service_helpers_and_tenant_action(self) -> None:
        service = AuditBizTraceEventService(
            table="audit_biz_trace_event",
            rsg=SimpleNamespace(),
        )
        self.assertEqual(
            service._normalize_max_rows("bad"), 500
        )  # pylint: disable=protected-access
        self.assertEqual(
            service._normalize_max_rows(-1), 500
        )  # pylint: disable=protected-access
        self.assertEqual(
            service._normalize_max_rows(6_000), 5_000
        )  # pylint: disable=protected-access
        self.assertIsNone(service._uuid_text(None))  # pylint: disable=protected-access
        self.assertTrue(
            service._datetime_text(datetime(2026, 1, 1)).endswith(
                "+00:00"
            )  # pylint: disable=protected-access
        )
        self.assertTrue(
            service._datetime_text(datetime(2026, 1, 1, tzinfo=timezone.utc)).endswith(
                "+00:00"
            )  # pylint: disable=protected-access
        )

        tenant_id = uuid.uuid4()
        service.list = AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=uuid.uuid4(),
                    tenant_id=None,
                    trace_id="trace-1",
                    span_id="span-1",
                    parent_span_id=None,
                    correlation_id="corr-1",
                    request_id="req-1",
                    source_plugin="com.vorsocomputing.mugen.acp",
                    entity_set="Users",
                    action_name="promote",
                    stage="finish",
                    status_code=200,
                    duration_ms=10,
                    details_json={"ok": True},
                    occurred_at=datetime(2026, 1, 1),
                )
            ]
        )

        payload, status = await service.action_inspect_trace(
            tenant_id=tenant_id,
            where={},
            auth_user_id=uuid.uuid4(),
            data=SimpleNamespace(
                trace_id=None,
                correlation_id="corr-1",
                request_id="req-1",
                stage="finish",
                max_rows=-1,
            ),
        )

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["Events"]), 1)
        filter_group = service.list.await_args.kwargs["filter_groups"][0]
        self.assertEqual(filter_group.where["tenant_id"], tenant_id)
        self.assertEqual(filter_group.where["correlation_id"], "corr-1")
        self.assertEqual(filter_group.where["request_id"], "req-1")
        self.assertEqual(filter_group.where["stage"], "finish")

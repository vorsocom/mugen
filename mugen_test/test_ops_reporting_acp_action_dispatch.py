"""Integration-style tests for ACP action dispatch with ops_reporting resources."""

from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
import uuid

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
            logging_gateway=SimpleNamespace(
                debug=lambda *_: None,
                error=lambda *_: None,
            ),
            get_ext_service=lambda *_: None,
            get_required_ext_service=lambda *_: None,
        )
        sys.modules["mugen.core.di"] = di_mod
        setattr(sys.modules["mugen.core"], "di", di_mod)


_bootstrap_namespace_packages()

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.plugin.acp.api.action import (  # noqa: E402
    dispatch_entity_action_tenant,
    dispatch_entity_set_action_tenant,
)
from mugen.core.plugin.ops_reporting.api.validation import (  # noqa: E402
    ExportJobBuildValidation,
    ExportJobCreateValidation,
    ExportJobVerifyValidation,
    MetricRunAggregationValidation,
    ReportSnapshotVerifyValidation,
)


class _FakeEdmType:
    def find_property(self, name: str):
        if name == "TenantId":
            return object()
        return None


class _FakeSchema:
    def get_type(self, _name: str) -> _FakeEdmType:
        return _FakeEdmType()


class _FakeOpsReportingService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def action_run_aggregation(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "aggregation_ok"}

    async def action_verify_snapshot(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "snapshot_verified"}

    async def action_create_export(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "export_created"}

    async def action_build_export(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "export_built"}

    async def action_verify_export(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "export_verified"}


class _FakeRegistry:
    def __init__(self, svc: _FakeOpsReportingService) -> None:
        self.schema = _FakeSchema()
        self._svc = svc
        self._resources = {
            "OpsReportingMetricDefinitions": SimpleNamespace(
                edm_type_name="OPSREPORTING.MetricDefinition",
                service_key="ops_reporting_svc",
                namespace="com.test.ops_reporting",
                capabilities=SimpleNamespace(
                    actions={
                        "run_aggregation": {
                            "schema": MetricRunAggregationValidation,
                        }
                    }
                ),
            ),
            "OpsReportingReportSnapshots": SimpleNamespace(
                edm_type_name="OPSREPORTING.ReportSnapshot",
                service_key="ops_reporting_svc",
                namespace="com.test.ops_reporting",
                capabilities=SimpleNamespace(
                    actions={
                        "verify_snapshot": {
                            "schema": ReportSnapshotVerifyValidation,
                        }
                    }
                ),
            ),
            "OpsReportingExportJobs": SimpleNamespace(
                edm_type_name="OPSREPORTING.ExportJob",
                service_key="ops_reporting_svc",
                namespace="com.test.ops_reporting",
                capabilities=SimpleNamespace(
                    actions={
                        "create_export": {
                            "schema": ExportJobCreateValidation,
                        },
                        "build_export": {
                            "schema": ExportJobBuildValidation,
                        },
                        "verify_export": {
                            "schema": ExportJobVerifyValidation,
                        },
                    }
                ),
            ),
        }

    def get_resource(self, entity_set: str):
        if entity_set not in self._resources:
            raise KeyError(entity_set)
        return self._resources[entity_set]

    def get_edm_service(self, service_key: str):
        if service_key != "ops_reporting_svc":
            raise KeyError(service_key)
        return self._svc


class TestOpsReportingAcpActionDispatch(unittest.IsolatedAsyncioTestCase):
    """Tests ACP tenant action dispatch integration with ops_reporting actions."""

    async def test_dispatch_run_aggregation_action_validates_payload(self) -> None:
        app = Quart("ops_reporting_run_aggregation_dispatch_test")

        tenant_id = uuid.uuid4()
        metric_id = uuid.uuid4()
        auth_user = uuid.uuid4()

        fake_service = _FakeOpsReportingService()
        registry = _FakeRegistry(fake_service)

        request_path = (
            f"/api/core/acp/v1/tenants/{tenant_id}/OpsReportingMetricDefinitions/"
            f"{metric_id}/$action/run_aggregation"
        )
        async with app.test_request_context(
            request_path,
            method="POST",
            json={
                "RowVersion": 4,
                "BucketMinutes": 30,
            },
        ):
            result = await dispatch_entity_action_tenant.__wrapped__(
                tenant_id=str(tenant_id),
                entity_set="OpsReportingMetricDefinitions",
                entity_id=str(metric_id),
                action="run_aggregation",
                auth_user=str(auth_user),
                logger_provider=lambda: SimpleNamespace(
                    debug=lambda *_: None,
                    error=lambda *_: None,
                ),
                registry_provider=lambda: registry,
            )

        self.assertEqual(result, {"status": "aggregation_ok"})
        call = fake_service.calls[0]
        self.assertEqual(call["tenant_id"], tenant_id)
        self.assertEqual(call["entity_id"], metric_id)
        self.assertEqual(call["where"], {"tenant_id": tenant_id, "id": metric_id})
        self.assertEqual(call["auth_user_id"], auth_user)
        self.assertIsInstance(call["data"], MetricRunAggregationValidation)
        self.assertEqual(call["data"].row_version, 4)
        self.assertEqual(call["data"].bucket_minutes, 30)

    async def test_dispatch_verify_snapshot_action_validates_payload(self) -> None:
        app = Quart("ops_reporting_verify_snapshot_dispatch_test")

        tenant_id = uuid.uuid4()
        snapshot_id = uuid.uuid4()
        auth_user = uuid.uuid4()

        fake_service = _FakeOpsReportingService()
        registry = _FakeRegistry(fake_service)

        request_path = (
            f"/api/core/acp/v1/tenants/{tenant_id}/OpsReportingReportSnapshots/"
            f"{snapshot_id}/$action/verify_snapshot"
        )
        async with app.test_request_context(
            request_path,
            method="POST",
            json={
                "RequireClean": True,
            },
        ):
            result = await dispatch_entity_action_tenant.__wrapped__(
                tenant_id=str(tenant_id),
                entity_set="OpsReportingReportSnapshots",
                entity_id=str(snapshot_id),
                action="verify_snapshot",
                auth_user=str(auth_user),
                logger_provider=lambda: SimpleNamespace(
                    debug=lambda *_: None,
                    error=lambda *_: None,
                ),
                registry_provider=lambda: registry,
            )

        self.assertEqual(result, {"status": "snapshot_verified"})
        call = fake_service.calls[0]
        self.assertEqual(call["tenant_id"], tenant_id)
        self.assertEqual(call["entity_id"], snapshot_id)
        self.assertEqual(call["where"], {"tenant_id": tenant_id, "id": snapshot_id})
        self.assertEqual(call["auth_user_id"], auth_user)
        self.assertIsInstance(call["data"], ReportSnapshotVerifyValidation)
        self.assertTrue(call["data"].require_clean)

    async def test_dispatch_create_export_set_action_validates_payload(self) -> None:
        app = Quart("ops_reporting_create_export_dispatch_test")

        tenant_id = uuid.uuid4()
        auth_user = uuid.uuid4()
        snapshot_id = uuid.uuid4()

        fake_service = _FakeOpsReportingService()
        registry = _FakeRegistry(fake_service)

        request_path = (
            f"/api/core/acp/v1/tenants/{tenant_id}/"
            "OpsReportingExportJobs/$action/create_export"
        )
        async with app.test_request_context(
            request_path,
            method="POST",
            json={
                "TraceId": "trace-123",
                "ExportType": "report_snapshot_pack",
                "SpecJson": {
                    "ResourceRefs": {
                        "OpsReportingReportSnapshots": [str(snapshot_id)],
                    }
                },
            },
        ):
            result = await dispatch_entity_set_action_tenant.__wrapped__(
                tenant_id=str(tenant_id),
                entity_set="OpsReportingExportJobs",
                action="create_export",
                auth_user=str(auth_user),
                logger_provider=lambda: SimpleNamespace(
                    debug=lambda *_: None,
                    error=lambda *_: None,
                ),
                registry_provider=lambda: registry,
            )

        self.assertEqual(result, {"status": "export_created"})
        call = fake_service.calls[0]
        self.assertEqual(call["tenant_id"], tenant_id)
        self.assertEqual(call["where"], {"tenant_id": tenant_id})
        self.assertEqual(call["auth_user_id"], auth_user)
        self.assertIsInstance(call["data"], ExportJobCreateValidation)
        self.assertEqual(call["data"].trace_id, "trace-123")

    async def test_dispatch_build_and_verify_export_actions_validate_payload(
        self,
    ) -> None:
        app = Quart("ops_reporting_build_verify_export_dispatch_test")

        tenant_id = uuid.uuid4()
        export_job_id = uuid.uuid4()
        auth_user = uuid.uuid4()

        fake_service = _FakeOpsReportingService()
        registry = _FakeRegistry(fake_service)

        build_path = (
            f"/api/core/acp/v1/tenants/{tenant_id}/OpsReportingExportJobs/"
            f"{export_job_id}/$action/build_export"
        )
        async with app.test_request_context(
            build_path,
            method="POST",
            json={
                "RowVersion": 3,
                "Force": True,
            },
        ):
            build_result = await dispatch_entity_action_tenant.__wrapped__(
                tenant_id=str(tenant_id),
                entity_set="OpsReportingExportJobs",
                entity_id=str(export_job_id),
                action="build_export",
                auth_user=str(auth_user),
                logger_provider=lambda: SimpleNamespace(
                    debug=lambda *_: None,
                    error=lambda *_: None,
                ),
                registry_provider=lambda: registry,
            )

        verify_path = (
            f"/api/core/acp/v1/tenants/{tenant_id}/OpsReportingExportJobs/"
            f"{export_job_id}/$action/verify_export"
        )
        async with app.test_request_context(
            verify_path,
            method="POST",
            json={
                "RequireClean": True,
            },
        ):
            verify_result = await dispatch_entity_action_tenant.__wrapped__(
                tenant_id=str(tenant_id),
                entity_set="OpsReportingExportJobs",
                entity_id=str(export_job_id),
                action="verify_export",
                auth_user=str(auth_user),
                logger_provider=lambda: SimpleNamespace(
                    debug=lambda *_: None,
                    error=lambda *_: None,
                ),
                registry_provider=lambda: registry,
            )

        self.assertEqual(build_result, {"status": "export_built"})
        self.assertEqual(verify_result, {"status": "export_verified"})

        build_call = fake_service.calls[0]
        self.assertIsInstance(build_call["data"], ExportJobBuildValidation)
        self.assertEqual(build_call["entity_id"], export_job_id)
        self.assertEqual(build_call["data"].row_version, 3)
        self.assertTrue(build_call["data"].force)

        verify_call = fake_service.calls[1]
        self.assertIsInstance(verify_call["data"], ExportJobVerifyValidation)
        self.assertEqual(verify_call["entity_id"], export_job_id)
        self.assertTrue(verify_call["data"].require_clean)

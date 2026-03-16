"""Integration-style tests for ACP action dispatch with ops_workflow resources."""

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
from mugen.core.plugin.ops_workflow.api.validation import (  # noqa: E402
    WorkflowAdvanceValidation,
    WorkflowCompensateValidation,
    WorkflowDecisionRequestOpenValidation,
    WorkflowDecisionRequestResolveValidation,
    WorkflowReplayValidation,
)


class _FakeEdmType:
    def find_property(self, name: str):
        if name == "TenantId":
            return object()
        return None


class _FakeSchema:
    def get_type(self, _name: str) -> _FakeEdmType:
        return _FakeEdmType()


class _FakeWorkflowInstanceService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def action_advance(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "ok"}

    async def action_replay(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "replayed"}

    async def action_compensate(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "compensated"}


class _FakeRegistry:
    def __init__(self, svc: _FakeWorkflowInstanceService) -> None:
        self.schema = _FakeSchema()
        self._svc = svc
        self._resource = SimpleNamespace(
            edm_type_name="OPSWORKFLOW.WorkflowInstance",
            service_key="workflow_instance_svc",
            namespace="com.test.ops_workflow",
            capabilities=SimpleNamespace(
                actions={
                    "advance": {
                        "schema": WorkflowAdvanceValidation,
                    },
                    "replay": {
                        "schema": WorkflowReplayValidation,
                    },
                    "compensate": {
                        "schema": WorkflowCompensateValidation,
                    },
                }
            ),
        )

    def get_resource(self, entity_set: str):
        if entity_set != "OpsWorkflowInstances":
            raise KeyError(entity_set)
        return self._resource

    def get_edm_service(self, service_key: str):
        if service_key != "workflow_instance_svc":
            raise KeyError(service_key)
        return self._svc


class _FakeDecisionRequestService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def action_open(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "opened"}

    async def action_resolve(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "resolved"}


class _FakeDecisionRequestRegistry:
    def __init__(self, svc: _FakeDecisionRequestService) -> None:
        self.schema = _FakeSchema()
        self._svc = svc
        self._resource = SimpleNamespace(
            edm_type_name="OPSWORKFLOW.WorkflowDecisionRequest",
            service_key="workflow_decision_request_svc",
            namespace="com.test.ops_workflow",
            capabilities=SimpleNamespace(
                actions={
                    "open": {
                        "schema": WorkflowDecisionRequestOpenValidation,
                    },
                    "resolve": {
                        "schema": WorkflowDecisionRequestResolveValidation,
                    },
                }
            ),
        )

    def get_resource(self, entity_set: str):
        if entity_set != "OpsWorkflowDecisionRequests":
            raise KeyError(entity_set)
        return self._resource

    def get_edm_service(self, service_key: str):
        if service_key != "workflow_decision_request_svc":
            raise KeyError(service_key)
        return self._svc


class TestOpsWorkflowAcpActionDispatch(unittest.IsolatedAsyncioTestCase):
    """Tests ACP tenant action dispatch integration with ops_workflow actions."""

    async def test_dispatch_calls_action_handler_with_validated_payload(self) -> None:
        app = Quart("ops_workflow_action_dispatch_test")

        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        auth_user = uuid.uuid4()

        fake_service = _FakeWorkflowInstanceService()
        registry = _FakeRegistry(fake_service)

        request_path = (
            f"/api/core/acp/v1/tenants/{tenant_id}/OpsWorkflowInstances/{instance_id}"
            "/$action/advance"
        )
        async with app.test_request_context(
            request_path,
            method="POST",
            json={
                "RowVersion": 7,
                "TransitionKey": "manager_approval",
                "Note": "advance workflow",
            },
        ):
            result = await dispatch_entity_action_tenant.__wrapped__(
                tenant_id=str(tenant_id),
                entity_set="OpsWorkflowInstances",
                entity_id=str(instance_id),
                action="advance",
                auth_user=str(auth_user),
                logger_provider=lambda: SimpleNamespace(
                    debug=lambda *_: None,
                    error=lambda *_: None,
                ),
                registry_provider=lambda: registry,
            )

        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(len(fake_service.calls), 1)

        call = fake_service.calls[0]
        self.assertEqual(call["tenant_id"], tenant_id)
        self.assertEqual(call["entity_id"], instance_id)
        self.assertEqual(call["where"], {"tenant_id": tenant_id, "id": instance_id})
        self.assertEqual(call["auth_user_id"], auth_user)
        self.assertIsInstance(call["data"], WorkflowAdvanceValidation)
        self.assertEqual(call["data"].row_version, 7)
        self.assertEqual(call["data"].transition_key, "manager_approval")

    async def test_dispatch_replay_action_validates_payload(self) -> None:
        app = Quart("ops_workflow_replay_action_dispatch_test")
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        auth_user = uuid.uuid4()

        fake_service = _FakeWorkflowInstanceService()
        registry = _FakeRegistry(fake_service)

        request_path = (
            f"/api/core/acp/v1/tenants/{tenant_id}/OpsWorkflowInstances/{instance_id}"
            "/$action/replay"
        )
        async with app.test_request_context(
            request_path,
            method="POST",
            json={"Repair": True},
        ):
            result = await dispatch_entity_action_tenant.__wrapped__(
                tenant_id=str(tenant_id),
                entity_set="OpsWorkflowInstances",
                entity_id=str(instance_id),
                action="replay",
                auth_user=str(auth_user),
                logger_provider=lambda: SimpleNamespace(
                    debug=lambda *_: None,
                    error=lambda *_: None,
                ),
                registry_provider=lambda: registry,
            )

        self.assertEqual(result, {"status": "replayed"})
        call = fake_service.calls[0]
        self.assertIsInstance(call["data"], WorkflowReplayValidation)
        self.assertTrue(call["data"].repair)

    async def test_dispatch_compensate_action_validates_payload(self) -> None:
        app = Quart("ops_workflow_compensate_action_dispatch_test")
        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        auth_user = uuid.uuid4()

        fake_service = _FakeWorkflowInstanceService()
        registry = _FakeRegistry(fake_service)

        request_path = (
            f"/api/core/acp/v1/tenants/{tenant_id}/OpsWorkflowInstances/{instance_id}"
            "/$action/compensate"
        )
        async with app.test_request_context(
            request_path,
            method="POST",
            json={"RowVersion": 3, "TransitionKey": "rollback"},
        ):
            result = await dispatch_entity_action_tenant.__wrapped__(
                tenant_id=str(tenant_id),
                entity_set="OpsWorkflowInstances",
                entity_id=str(instance_id),
                action="compensate",
                auth_user=str(auth_user),
                logger_provider=lambda: SimpleNamespace(
                    debug=lambda *_: None,
                    error=lambda *_: None,
                ),
                registry_provider=lambda: registry,
            )

        self.assertEqual(result, {"status": "compensated"})
        call = fake_service.calls[0]
        self.assertIsInstance(call["data"], WorkflowCompensateValidation)
        self.assertEqual(call["data"].row_version, 3)
        self.assertEqual(call["data"].transition_key, "rollback")

    async def test_dispatch_decision_request_open_set_action_validates_payload(
        self,
    ) -> None:
        app = Quart("ops_workflow_decision_request_open_dispatch_test")
        tenant_id = uuid.uuid4()
        auth_user = uuid.uuid4()
        workflow_instance_id = uuid.uuid4()

        fake_service = _FakeDecisionRequestService()
        registry = _FakeDecisionRequestRegistry(fake_service)

        request_path = (
            f"/api/core/acp/v1/tenants/{tenant_id}/"
            "OpsWorkflowDecisionRequests/$action/open"
        )
        async with app.test_request_context(
            request_path,
            method="POST",
            json={
                "TemplateKey": "workflow.approval",
                "WorkflowInstanceId": str(workflow_instance_id),
            },
        ):
            result = await dispatch_entity_set_action_tenant.__wrapped__(
                tenant_id=str(tenant_id),
                entity_set="OpsWorkflowDecisionRequests",
                action="open",
                auth_user=str(auth_user),
                logger_provider=lambda: SimpleNamespace(
                    debug=lambda *_: None,
                    error=lambda *_: None,
                ),
                registry_provider=lambda: registry,
            )

        self.assertEqual(result, {"status": "opened"})
        call = fake_service.calls[0]
        self.assertEqual(call["tenant_id"], tenant_id)
        self.assertEqual(call["where"], {"tenant_id": tenant_id})
        self.assertIsInstance(call["data"], WorkflowDecisionRequestOpenValidation)
        self.assertEqual(call["data"].template_key, "workflow.approval")
        self.assertEqual(call["data"].workflow_instance_id, workflow_instance_id)

    async def test_dispatch_decision_request_resolve_action_validates_payload(
        self,
    ) -> None:
        app = Quart("ops_workflow_decision_request_resolve_dispatch_test")
        tenant_id = uuid.uuid4()
        decision_request_id = uuid.uuid4()
        auth_user = uuid.uuid4()

        fake_service = _FakeDecisionRequestService()
        registry = _FakeDecisionRequestRegistry(fake_service)

        request_path = (
            f"/api/core/acp/v1/tenants/{tenant_id}/OpsWorkflowDecisionRequests/"
            f"{decision_request_id}/$action/resolve"
        )
        async with app.test_request_context(
            request_path,
            method="POST",
            json={
                "RowVersion": 5,
                "Outcome": "approved",
            },
        ):
            result = await dispatch_entity_action_tenant.__wrapped__(
                tenant_id=str(tenant_id),
                entity_set="OpsWorkflowDecisionRequests",
                entity_id=str(decision_request_id),
                action="resolve",
                auth_user=str(auth_user),
                logger_provider=lambda: SimpleNamespace(
                    debug=lambda *_: None,
                    error=lambda *_: None,
                ),
                registry_provider=lambda: registry,
            )

        self.assertEqual(result, {"status": "resolved"})
        call = fake_service.calls[0]
        self.assertEqual(call["tenant_id"], tenant_id)
        self.assertEqual(call["entity_id"], decision_request_id)
        self.assertEqual(
            call["where"],
            {"tenant_id": tenant_id, "id": decision_request_id},
        )
        self.assertIsInstance(call["data"], WorkflowDecisionRequestResolveValidation)
        self.assertEqual(call["data"].row_version, 5)
        self.assertEqual(call["data"].outcome, "approved")

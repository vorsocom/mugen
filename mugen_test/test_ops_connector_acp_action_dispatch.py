"""Integration-style tests for ACP action dispatch with ops_connector resources."""

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
from mugen.core.plugin.acp.api.action import dispatch_entity_action_tenant  # noqa: E402
from mugen.core.plugin.ops_connector.api.validation import (  # noqa: E402
    ConnectorInstanceInvokeValidation,
    ConnectorInstanceTestConnectionValidation,
)


class _FakeEdmType:
    def find_property(self, name: str):
        if name == "TenantId":
            return object()
        return None


class _FakeSchema:
    def get_type(self, _name: str) -> _FakeEdmType:
        return _FakeEdmType()


class _FakeConnectorService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def action_test_connection(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "tested"}, 200

    async def action_invoke(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "invoked"}, 200


class _FakeRegistry:
    def __init__(self, svc: _FakeConnectorService) -> None:
        self.schema = _FakeSchema()
        self._svc = svc
        self._resource = SimpleNamespace(
            edm_type_name="OPSCONNECTOR.ConnectorInstance",
            service_key="ops_connector_svc",
            namespace="com.test.ops_connector",
            capabilities=SimpleNamespace(
                actions={
                    "test_connection": {
                        "schema": ConnectorInstanceTestConnectionValidation,
                    },
                    "invoke": {
                        "schema": ConnectorInstanceInvokeValidation,
                    },
                }
            ),
        )

    def get_resource(self, entity_set: str):
        if entity_set != "OpsConnectorInstances":
            raise KeyError(entity_set)
        return self._resource

    def get_edm_service(self, service_key: str):
        if service_key != "ops_connector_svc":
            raise KeyError(service_key)
        return self._svc


class TestOpsConnectorAcpActionDispatch(unittest.IsolatedAsyncioTestCase):
    """Tests ACP tenant action dispatch integration with ops_connector actions."""

    async def test_dispatch_test_connection_action_validates_payload(self) -> None:
        app = Quart("ops_connector_test_connection_dispatch")

        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        auth_user = uuid.uuid4()

        fake_service = _FakeConnectorService()
        registry = _FakeRegistry(fake_service)

        request_path = (
            f"/api/core/acp/v1/tenants/{tenant_id}/OpsConnectorInstances/"
            f"{instance_id}/$action/test_connection"
        )
        async with app.test_request_context(
            request_path,
            method="POST",
            json={
                "RowVersion": 4,
                "TraceId": "trace-test",
            },
        ):
            result = await dispatch_entity_action_tenant.__wrapped__(
                tenant_id=str(tenant_id),
                entity_set="OpsConnectorInstances",
                entity_id=str(instance_id),
                action="test_connection",
                auth_user=str(auth_user),
                logger_provider=lambda: SimpleNamespace(
                    debug=lambda *_: None,
                    error=lambda *_: None,
                ),
                registry_provider=lambda: registry,
            )

        self.assertEqual(result, ({"status": "tested"}, 200))
        call = fake_service.calls[0]
        self.assertEqual(call["tenant_id"], tenant_id)
        self.assertEqual(call["entity_id"], instance_id)
        self.assertEqual(call["where"], {"tenant_id": tenant_id, "id": instance_id})
        self.assertEqual(call["auth_user_id"], auth_user)
        self.assertIsInstance(call["data"], ConnectorInstanceTestConnectionValidation)
        self.assertEqual(call["data"].row_version, 4)
        self.assertEqual(call["data"].trace_id, "trace-test")

    async def test_dispatch_invoke_action_validates_payload(self) -> None:
        app = Quart("ops_connector_invoke_dispatch")

        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()
        auth_user = uuid.uuid4()

        fake_service = _FakeConnectorService()
        registry = _FakeRegistry(fake_service)

        request_path = (
            f"/api/core/acp/v1/tenants/{tenant_id}/OpsConnectorInstances/"
            f"{instance_id}/$action/invoke"
        )
        async with app.test_request_context(
            request_path,
            method="POST",
            json={
                "RowVersion": 6,
                "CapabilityName": "get_jwks",
                "InputJson": {"Probe": True},
                "TraceId": "trace-invoke",
                "ClientActionKey": "invoke-key-1",
            },
        ):
            result = await dispatch_entity_action_tenant.__wrapped__(
                tenant_id=str(tenant_id),
                entity_set="OpsConnectorInstances",
                entity_id=str(instance_id),
                action="invoke",
                auth_user=str(auth_user),
                logger_provider=lambda: SimpleNamespace(
                    debug=lambda *_: None,
                    error=lambda *_: None,
                ),
                registry_provider=lambda: registry,
            )

        self.assertEqual(result, ({"status": "invoked"}, 200))
        call = fake_service.calls[0]
        self.assertIsInstance(call["data"], ConnectorInstanceInvokeValidation)
        self.assertEqual(call["data"].row_version, 6)
        self.assertEqual(call["data"].capability_name, "get_jwks")
        self.assertEqual(call["data"].input_json, {"Probe": True})
        self.assertEqual(call["data"].trace_id, "trace-invoke")
        self.assertEqual(call["data"].client_action_key, "invoke-key-1")

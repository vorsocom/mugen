"""Integration-style tests for ACP action dispatch with ops_sla resources."""

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
        )
        sys.modules["mugen.core.di"] = di_mod
        setattr(sys.modules["mugen.core"], "di", di_mod)


_bootstrap_namespace_packages()

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.plugin.acp.api.action import (  # noqa: E402
    dispatch_entity_action_tenant,
)
from mugen.core.plugin.ops_sla.api.validation import (  # noqa: E402
    SlaClockStartValidation,
)


class _FakeEdmType:
    def find_property(self, name: str):
        if name == "TenantId":
            return object()
        return None


class _FakeSchema:
    def get_type(self, _name: str) -> _FakeEdmType:
        return _FakeEdmType()


class _FakeClockService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def action_start_clock(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "ok"}


class _FakeRegistry:
    def __init__(self, svc: _FakeClockService) -> None:
        self.schema = _FakeSchema()
        self._svc = svc
        self._resource = SimpleNamespace(
            edm_type_name="OPSSLA.SlaClock",
            service_key="clock_svc",
            namespace="com.test.ops_sla",
            capabilities=SimpleNamespace(
                actions={
                    "start_clock": {
                        "schema": SlaClockStartValidation,
                    }
                }
            ),
        )

    def get_resource(self, entity_set: str):
        if entity_set != "OpsSlaClocks":
            raise KeyError(entity_set)
        return self._resource

    def get_edm_service(self, service_key: str):
        if service_key != "clock_svc":
            raise KeyError(service_key)
        return self._svc


class TestOpsSlaAcpActionDispatch(unittest.IsolatedAsyncioTestCase):
    """Tests ACP tenant action dispatch integration with ops_sla actions."""

    async def test_dispatch_calls_action_handler_with_validated_payload(self) -> None:
        app = Quart("ops_sla_action_dispatch_test")

        tenant_id = uuid.uuid4()
        clock_id = uuid.uuid4()
        auth_user = uuid.uuid4()

        fake_service = _FakeClockService()
        registry = _FakeRegistry(fake_service)

        request_path = (
            f"/api/core/acp/v1/tenants/{tenant_id}/OpsSlaClocks/{clock_id}"
            "/$action/start_clock"
        )
        async with app.test_request_context(
            request_path,
            method="POST",
            json={"RowVersion": 4},
        ):
            result = await dispatch_entity_action_tenant.__wrapped__(
                tenant_id=str(tenant_id),
                entity_set="OpsSlaClocks",
                entity_id=str(clock_id),
                action="start_clock",
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
        self.assertEqual(call["entity_id"], clock_id)
        self.assertEqual(call["where"], {"tenant_id": tenant_id, "id": clock_id})
        self.assertEqual(call["auth_user_id"], auth_user)
        self.assertIsInstance(call["data"], SlaClockStartValidation)
        self.assertEqual(call["data"].row_version, 4)

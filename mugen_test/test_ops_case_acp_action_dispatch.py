"""Integration-style tests for ACP action dispatch with ops_case resources."""

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
from mugen.core.plugin.acp.api.action import (
    dispatch_entity_action_tenant,
)
from mugen.core.plugin.ops_case.api.validation import (
    CaseResolveValidation,
)


class _FakeEdmType:
    def find_property(self, name: str):
        if name == "TenantId":
            return object()
        return None


class _FakeSchema:
    def get_type(self, _name: str) -> _FakeEdmType:
        return _FakeEdmType()


class _FakeCaseService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def action_resolve(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "ok"}


class _FakeRegistry:
    def __init__(self, svc: _FakeCaseService) -> None:
        self.schema = _FakeSchema()
        self._svc = svc
        self._resource = SimpleNamespace(
            edm_type_name="OPSCASE.Case",
            service_key="case_svc",
            namespace="com.test.ops_case",
            capabilities=SimpleNamespace(
                actions={
                    "resolve": {
                        "schema": CaseResolveValidation,
                    }
                }
            ),
        )

    def get_resource(self, entity_set: str):
        if entity_set != "OpsCases":
            raise KeyError(entity_set)
        return self._resource

    def get_edm_service(self, service_key: str):
        if service_key != "case_svc":
            raise KeyError(service_key)
        return self._svc


class TestOpsCaseAcpActionDispatch(unittest.IsolatedAsyncioTestCase):
    """Tests ACP tenant action dispatch integration with ops_case actions."""

    async def test_dispatch_calls_action_handler_with_validated_payload(self) -> None:
        app = Quart("ops_case_action_dispatch_test")

        tenant_id = uuid.uuid4()
        case_id = uuid.uuid4()
        auth_user = uuid.uuid4()

        fake_service = _FakeCaseService()
        registry = _FakeRegistry(fake_service)

        request_path = (
            f"/api/core/acp/v1/tenants/{tenant_id}/OpsCases/{case_id}/$action/resolve"
        )
        async with app.test_request_context(
            request_path,
            method="POST",
            json={
                "RowVersion": 7,
                "ResolutionSummary": "Fixed upstream dependency timeout",
            },
        ):
            result = await dispatch_entity_action_tenant.__wrapped__(
                tenant_id=str(tenant_id),
                entity_set="OpsCases",
                entity_id=str(case_id),
                action="resolve",
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
        self.assertEqual(call["entity_id"], case_id)
        self.assertEqual(call["where"], {"tenant_id": tenant_id, "id": case_id})
        self.assertEqual(call["auth_user_id"], auth_user)
        self.assertIsInstance(call["data"], CaseResolveValidation)
        self.assertEqual(call["data"].row_version, 7)
        self.assertEqual(
            call["data"].resolution_summary,
            "Fixed upstream dependency timeout",
        )

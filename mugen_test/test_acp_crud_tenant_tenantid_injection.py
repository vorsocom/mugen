"""Integration-style tests for tenant create schema TenantId injection."""

from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import AsyncMock, patch
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
from mugen.core.plugin.acp.api.crud import create_entity_tenant
from mugen.core.plugin.ops_case.api.validation import CaseLinkCreateValidation


class _FakeEdmType:
    def find_property(self, name: str):
        if name == "TenantId":
            return object()
        return None


class _FakeSchema:
    def get_type(self, _name: str) -> _FakeEdmType:
        return _FakeEdmType()


class _FakeRegistry:
    def __init__(self, svc) -> None:
        self.schema = _FakeSchema()
        self._svc = svc
        self._resource = SimpleNamespace(
            edm_type_name="OPSCASE.CaseLink",
            service_key="case_link_svc",
            namespace="com.test.ops_case",
            crud=SimpleNamespace(create_schema=CaseLinkCreateValidation),
        )

    def get_resource(self, entity_set: str):
        if entity_set != "OpsCaseLinks":
            raise KeyError(entity_set)
        return self._resource

    def get_edm_service(self, service_key: str):
        if service_key != "case_link_svc":
            raise KeyError(service_key)
        return self._svc


class TestAcpCrudTenantTenantIdInjection(unittest.IsolatedAsyncioTestCase):
    """Tests tenant create path injects TenantId for typed create schemas."""

    async def test_tenant_create_injects_tenantid_for_schema_validation(self) -> None:
        app = Quart("acp_crud_tenant_tenantid_injection_test")
        tenant_id = uuid.uuid4()
        auth_user = uuid.uuid4()
        case_id = uuid.uuid4()

        fake_service = SimpleNamespace(
            create=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
        )
        registry = _FakeRegistry(fake_service)

        request_path = f"/api/core/acp/v1/tenants/{tenant_id}/OpsCaseLinks"
        async with app.test_request_context(
            request_path,
            method="POST",
            json={
                "CaseId": str(case_id),
                "LinkType": "invoice",
                "TargetType": "billing.invoice",
                "TargetRef": "INV-1001",
            },
        ):
            with patch(
                "mugen.core.plugin.acp.api.crud.emit_audit_event",
                new=AsyncMock(return_value=None),
            ):
                _, status = await create_entity_tenant.__wrapped__(
                    tenant_id=str(tenant_id),
                    entity_set="OpsCaseLinks",
                    auth_user=str(auth_user),
                    logger_provider=lambda: SimpleNamespace(
                        debug=lambda *_: None,
                        error=lambda *_: None,
                    ),
                    registry_provider=lambda: registry,
                )

        self.assertEqual(status, 201)
        fake_service.create.assert_awaited_once()
        payload = fake_service.create.await_args.args[0]
        self.assertEqual(payload["tenant_id"], tenant_id)
        self.assertEqual(payload["case_id"], case_id)
        self.assertEqual(payload["target_ref"], "INV-1001")

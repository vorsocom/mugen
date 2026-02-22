"""Lifecycle action tests for ACP Tenant and TenantMembership services."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import SQLAlchemyError


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
            logging_gateway=SimpleNamespace(),
            get_required_ext_service=lambda *_: None,
        )
        sys.modules["mugen.core.di"] = di_mod
        setattr(sys.modules["mugen.core"], "di", di_mod)


_bootstrap_namespace_packages()

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.acp.service import tenant as tenant_mod
from mugen.core.plugin.acp.service import tenant_membership as membership_mod
from mugen.core.plugin.acp.service.tenant import TenantService
from mugen.core.plugin.acp.service.tenant_membership import TenantMembershipService


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


def _tenant_service() -> TenantService:
    svc = TenantService.__new__(TenantService)
    svc.get = AsyncMock()
    svc.update_with_row_version = AsyncMock()
    return svc


def _membership_service() -> TenantMembershipService:
    svc = TenantMembershipService.__new__(TenantMembershipService)
    svc.get = AsyncMock()
    svc.update_with_row_version = AsyncMock()
    svc.delete_with_row_version = AsyncMock()
    return svc


class TestMugenAcpServiceTenantLifecycle(unittest.IsolatedAsyncioTestCase):
    """Covers tenant and tenant membership lifecycle action behavior."""

    async def test_tenant_deactivate_and_reactivate_paths(self) -> None:
        svc = _tenant_service()
        entity_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        data = SimpleNamespace(row_version=7)

        svc.get = AsyncMock(return_value=SimpleNamespace(id=entity_id, status="active"))
        svc.update_with_row_version = AsyncMock(
            return_value=SimpleNamespace(id=entity_id, status="suspended")
        )
        payload, status = await TenantService.entity_action_deactivate(
            svc,
            entity_id=entity_id,
            auth_user_id=auth_user_id,
            data=data,
        )
        self.assertEqual((payload, status), ("", 204))

        svc.get = AsyncMock(
            return_value=SimpleNamespace(id=entity_id, status="suspended")
        )
        svc.update_with_row_version = AsyncMock(
            return_value=SimpleNamespace(id=entity_id, status="active")
        )
        payload, status = await TenantService.entity_action_reactivate(
            svc,
            entity_id=entity_id,
            auth_user_id=auth_user_id,
            data=data,
        )
        self.assertEqual((payload, status), ("", 204))

        with patch.object(tenant_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await TenantService.entity_action_deactivate(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await TenantService.entity_action_deactivate(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(
                return_value=SimpleNamespace(id=entity_id, status="suspended")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantService.entity_action_deactivate(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.get = AsyncMock(
                return_value=SimpleNamespace(id=entity_id, status="active")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantService.entity_action_reactivate(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.get = AsyncMock(
                return_value=SimpleNamespace(id=entity_id, status="active")
            )
            svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("table")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantService.entity_action_deactivate(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await TenantService.entity_action_deactivate(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await TenantService.entity_action_deactivate(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

    async def test_membership_suspend_unsuspend_remove_paths(self) -> None:
        svc = _membership_service()
        tenant_id = uuid.uuid4()
        membership_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": membership_id}
        data = SimpleNamespace(row_version=3)

        svc.get = AsyncMock(
            return_value=SimpleNamespace(id=membership_id, status="active")
        )
        svc.update_with_row_version = AsyncMock(
            return_value=SimpleNamespace(id=membership_id, status="suspended")
        )
        payload, status = await TenantMembershipService.action_suspend(
            svc,
            tenant_id=tenant_id,
            entity_id=membership_id,
            where=where,
            auth_user_id=auth_user_id,
            data=data,
        )
        self.assertEqual((payload, status), ("", 204))

        svc.get = AsyncMock(
            return_value=SimpleNamespace(id=membership_id, status="suspended")
        )
        svc.update_with_row_version = AsyncMock(
            return_value=SimpleNamespace(id=membership_id, status="active")
        )
        payload, status = await TenantMembershipService.action_unsuspend(
            svc,
            tenant_id=tenant_id,
            entity_id=membership_id,
            where=where,
            auth_user_id=auth_user_id,
            data=data,
        )
        self.assertEqual((payload, status), ("", 204))

        svc.delete_with_row_version = AsyncMock(return_value=SimpleNamespace(id=membership_id))
        payload, status = await TenantMembershipService.action_remove(
            svc,
            tenant_id=tenant_id,
            entity_id=membership_id,
            where=where,
            auth_user_id=auth_user_id,
            data=data,
        )
        self.assertEqual((payload, status), ("", 204))

        with patch.object(membership_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await TenantMembershipService.action_suspend(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=membership_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await TenantMembershipService.action_suspend(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=membership_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(
                return_value=SimpleNamespace(id=membership_id, status="invited")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantMembershipService.action_suspend(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=membership_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.get = AsyncMock(
                return_value=SimpleNamespace(id=membership_id, status="active")
            )
            svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("table")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantMembershipService.action_suspend(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=membership_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await TenantMembershipService.action_suspend(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=membership_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await TenantMembershipService.action_suspend(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=membership_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.delete_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("table")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await TenantMembershipService.action_remove(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=membership_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.delete_with_row_version = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await TenantMembershipService.action_remove(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=membership_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.delete_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await TenantMembershipService.action_remove(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=membership_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

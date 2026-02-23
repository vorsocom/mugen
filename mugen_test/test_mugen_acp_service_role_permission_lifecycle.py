"""Lifecycle action tests for ACP Role and core permission taxonomy services."""

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
from mugen.core.plugin.acp.service import permission_object as permission_object_mod
from mugen.core.plugin.acp.service import permission_type as permission_type_mod
from mugen.core.plugin.acp.service import role as role_mod
from mugen.core.plugin.acp.service.permission_object import PermissionObjectService
from mugen.core.plugin.acp.service.permission_type import PermissionTypeService
from mugen.core.plugin.acp.service.role import RoleService


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


def _role_service() -> RoleService:
    svc = RoleService.__new__(RoleService)
    svc.get = AsyncMock()
    svc.update_with_row_version = AsyncMock()
    return svc


def _permission_object_service() -> PermissionObjectService:
    svc = PermissionObjectService.__new__(PermissionObjectService)
    svc.get = AsyncMock()
    svc.update_with_row_version = AsyncMock()
    return svc


def _permission_type_service() -> PermissionTypeService:
    svc = PermissionTypeService.__new__(PermissionTypeService)
    svc.get = AsyncMock()
    svc.update_with_row_version = AsyncMock()
    return svc


class TestMugenAcpServiceRolePermissionLifecycle(unittest.IsolatedAsyncioTestCase):
    """Covers role and permission taxonomy lifecycle action behavior."""

    async def test_role_deprecate_and_reactivate_paths(self) -> None:
        svc = _role_service()
        tenant_id = uuid.uuid4()
        role_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": role_id}
        data = SimpleNamespace(row_version=2)

        svc.get = AsyncMock(return_value=SimpleNamespace(id=role_id, status="active"))
        svc.update_with_row_version = AsyncMock(
            return_value=SimpleNamespace(id=role_id, status="deprecated")
        )
        payload, status = await RoleService.action_deprecate(
            svc,
            tenant_id=tenant_id,
            entity_id=role_id,
            where=where,
            auth_user_id=auth_user_id,
            data=data,
        )
        self.assertEqual((payload, status), ("", 204))

        svc.get = AsyncMock(
            return_value=SimpleNamespace(id=role_id, status="deprecated")
        )
        svc.update_with_row_version = AsyncMock(
            return_value=SimpleNamespace(id=role_id, status="active")
        )
        payload, status = await RoleService.action_reactivate(
            svc,
            tenant_id=tenant_id,
            entity_id=role_id,
            where=where,
            auth_user_id=auth_user_id,
            data=data,
        )
        self.assertEqual((payload, status), ("", 204))

        with patch.object(role_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await RoleService.action_deprecate(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=role_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await RoleService.action_deprecate(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=role_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(
                return_value=SimpleNamespace(id=role_id, status="deprecated")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await RoleService.action_deprecate(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=role_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.get = AsyncMock(
                return_value=SimpleNamespace(id=role_id, status="active")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await RoleService.action_reactivate(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=role_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.get = AsyncMock(
                return_value=SimpleNamespace(id=role_id, status="active")
            )
            svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("table")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await RoleService.action_deprecate(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=role_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await RoleService.action_deprecate(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=role_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await RoleService.action_deprecate(
                    svc,
                    tenant_id=tenant_id,
                    entity_id=role_id,
                    where=where,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

    async def test_permission_object_deprecate_and_reactivate_paths(self) -> None:
        svc = _permission_object_service()
        entity_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        data = SimpleNamespace(row_version=11)

        svc.get = AsyncMock(return_value=SimpleNamespace(id=entity_id, status="active"))
        svc.update_with_row_version = AsyncMock(
            return_value=SimpleNamespace(id=entity_id, status="deprecated")
        )
        payload, status = await PermissionObjectService.entity_action_deprecate(
            svc,
            entity_id=entity_id,
            auth_user_id=auth_user_id,
            data=data,
        )
        self.assertEqual((payload, status), ("", 204))

        svc.get = AsyncMock(
            return_value=SimpleNamespace(id=entity_id, status="deprecated")
        )
        svc.update_with_row_version = AsyncMock(
            return_value=SimpleNamespace(id=entity_id, status="active")
        )
        payload, status = await PermissionObjectService.entity_action_reactivate(
            svc,
            entity_id=entity_id,
            auth_user_id=auth_user_id,
            data=data,
        )
        self.assertEqual((payload, status), ("", 204))

        with patch.object(permission_object_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await PermissionObjectService.entity_action_deprecate(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await PermissionObjectService.entity_action_deprecate(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(
                return_value=SimpleNamespace(id=entity_id, status="deprecated")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await PermissionObjectService.entity_action_deprecate(
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
                await PermissionObjectService.entity_action_reactivate(
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
                await PermissionObjectService.entity_action_deprecate(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await PermissionObjectService.entity_action_deprecate(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await PermissionObjectService.entity_action_deprecate(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

    async def test_permission_type_deprecate_and_reactivate_paths(self) -> None:
        svc = _permission_type_service()
        entity_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        data = SimpleNamespace(row_version=5)

        svc.get = AsyncMock(return_value=SimpleNamespace(id=entity_id, status="active"))
        svc.update_with_row_version = AsyncMock(
            return_value=SimpleNamespace(id=entity_id, status="deprecated")
        )
        payload, status = await PermissionTypeService.entity_action_deprecate(
            svc,
            entity_id=entity_id,
            auth_user_id=auth_user_id,
            data=data,
        )
        self.assertEqual((payload, status), ("", 204))

        svc.get = AsyncMock(
            return_value=SimpleNamespace(id=entity_id, status="deprecated")
        )
        svc.update_with_row_version = AsyncMock(
            return_value=SimpleNamespace(id=entity_id, status="active")
        )
        payload, status = await PermissionTypeService.entity_action_reactivate(
            svc,
            entity_id=entity_id,
            auth_user_id=auth_user_id,
            data=data,
        )
        self.assertEqual((payload, status), ("", 204))

        with patch.object(permission_type_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await PermissionTypeService.entity_action_deprecate(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await PermissionTypeService.entity_action_deprecate(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(
                return_value=SimpleNamespace(id=entity_id, status="deprecated")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await PermissionTypeService.entity_action_deprecate(
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
                await PermissionTypeService.entity_action_reactivate(
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
                await PermissionTypeService.entity_action_deprecate(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("db"))
            with self.assertRaises(_AbortCalled) as ex:
                await PermissionTypeService.entity_action_deprecate(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await PermissionTypeService.entity_action_deprecate(
                    svc,
                    entity_id=entity_id,
                    auth_user_id=auth_user_id,
                    data=data,
                )
            self.assertEqual(ex.exception.code, 404)


if __name__ == "__main__":
    unittest.main()

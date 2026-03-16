"""Tests RBAC payload validators used by ACP contrib wiring."""

from __future__ import annotations

import unittest
import uuid

from pydantic import ValidationError

from mugen.core.plugin.acp.api.validation.rbac import (
    GlobalPermissionEntryCreateValidation,
    GlobalRoleCreateValidation,
    GlobalRoleUpdateValidation,
    PermissionEntryCreateValidation,
    PermissionObjectCreateValidation,
    PermissionTypeCreateValidation,
    RoleCreateValidation,
    RoleUpdateValidation,
)


class TestMugenAcpValidationRbac(unittest.TestCase):
    """Covers branch paths in RBAC validation helpers."""

    def test_key_and_display_validators_strip_and_reject_empty_values(self) -> None:
        tenant_id = uuid.uuid4()

        global_role = GlobalRoleCreateValidation(
            namespace="  core  ",
            name="  admin  ",
            display_name="  Administrator  ",
        )
        self.assertEqual(global_role.namespace, "core")
        self.assertEqual(global_role.name, "admin")
        self.assertEqual(global_role.display_name, "Administrator")

        role = RoleCreateValidation(
            tenant_id=tenant_id,
            namespace="  core  ",
            name="  owner  ",
            display_name="  Owner  ",
        )
        self.assertEqual(role.namespace, "core")
        self.assertEqual(role.name, "owner")
        self.assertEqual(role.display_name, "Owner")

        permission_object = PermissionObjectCreateValidation(
            namespace="  core  ",
            name="  tenant  ",
        )
        self.assertEqual(permission_object.namespace, "core")
        self.assertEqual(permission_object.name, "tenant")

        permission_type = PermissionTypeCreateValidation(
            namespace="  core  ",
            name="  manage  ",
        )
        self.assertEqual(permission_type.namespace, "core")
        self.assertEqual(permission_type.name, "manage")

        global_role_update = GlobalRoleUpdateValidation(display_name="  New Label  ")
        self.assertEqual(global_role_update.display_name, "New Label")
        self.assertIsNone(GlobalRoleUpdateValidation(display_name=None).display_name)

        role_update = RoleUpdateValidation(display_name="  New Owner  ")
        self.assertEqual(role_update.display_name, "New Owner")
        self.assertIsNone(RoleUpdateValidation(display_name=None).display_name)

        with self.assertRaises(ValidationError):
            GlobalRoleCreateValidation(
                namespace=" ",
                name="admin",
                display_name="Administrator",
            )

        with self.assertRaises(ValidationError):
            GlobalRoleCreateValidation(
                namespace="core",
                name=" ",
                display_name="Administrator",
            )

        with self.assertRaises(ValidationError):
            GlobalRoleCreateValidation(
                namespace="core",
                name="admin",
                display_name=" ",
            )

        with self.assertRaises(ValidationError):
            GlobalRoleUpdateValidation(display_name=" ")

        with self.assertRaises(ValidationError):
            RoleUpdateValidation(display_name=" ")

    def test_entry_validators_require_ids_and_parse_uuid_values(self) -> None:
        tenant_id = uuid.uuid4()
        role_id = uuid.uuid4()
        global_role_id = uuid.uuid4()
        permission_object_id = uuid.uuid4()
        permission_type_id = uuid.uuid4()

        permission_entry = PermissionEntryCreateValidation(
            tenant_id=str(tenant_id),
            role_id=str(role_id),
            permission_object_id=str(permission_object_id),
            permission_type_id=str(permission_type_id),
            permitted=True,
        )
        self.assertEqual(permission_entry.tenant_id, tenant_id)
        self.assertEqual(permission_entry.role_id, role_id)
        self.assertEqual(permission_entry.permission_object_id, permission_object_id)
        self.assertEqual(permission_entry.permission_type_id, permission_type_id)

        global_permission_entry = GlobalPermissionEntryCreateValidation(
            global_role_id=str(global_role_id),
            permission_object_id=str(permission_object_id),
            permission_type_id=str(permission_type_id),
            permitted=False,
        )
        self.assertEqual(global_permission_entry.global_role_id, global_role_id)
        self.assertEqual(
            global_permission_entry.permission_object_id,
            permission_object_id,
        )
        self.assertEqual(
            global_permission_entry.permission_type_id,
            permission_type_id,
        )

        with self.assertRaises(ValidationError):
            PermissionEntryCreateValidation(
                tenant_id=str(tenant_id),
                permission_object_id=str(permission_object_id),
                permission_type_id=str(permission_type_id),
                permitted=True,
            )

        with self.assertRaises(ValidationError):
            PermissionEntryCreateValidation(
                tenant_id=str(tenant_id),
                role_id="bad-uuid",
                permission_object_id=str(permission_object_id),
                permission_type_id=str(permission_type_id),
                permitted=True,
            )

        with self.assertRaises(ValidationError):
            GlobalPermissionEntryCreateValidation(
                global_role_id="bad-uuid",
                permission_object_id=str(permission_object_id),
                permission_type_id=str(permission_type_id),
                permitted=True,
            )

"""Provides Pydantic validators for ACP RBAC CRUD payloads."""

__all__ = [
    "GlobalPermissionEntryCreateValidation",
    "GlobalPermissionEntryUpdateValidation",
    "GlobalRoleCreateValidation",
    "GlobalRoleUpdateValidation",
    "PermissionEntryCreateValidation",
    "PermissionEntryUpdateValidation",
    "PermissionObjectCreateValidation",
    "PermissionTypeCreateValidation",
    "RoleCreateValidation",
    "RoleUpdateValidation",
]

import uuid

from pydantic import ValidationInfo, field_validator

from mugen.core.plugin.acp.contract.api.validation import IValidationBase


def _validate_nonempty_trimmed(value: str, *, field_label: str) -> str:
    stripped = value.strip()
    if stripped == "":
        raise ValueError(f"{field_label} must be non-empty.")
    return stripped


class _NamespaceNameValidation(IValidationBase):
    namespace: str

    name: str

    @field_validator("namespace", "name")
    @classmethod
    def _validate_namespace_name(cls, value: str, info: ValidationInfo) -> str:
        label = "Namespace" if info.field_name == "namespace" else "Name"
        return _validate_nonempty_trimmed(value, field_label=label)


class GlobalRoleCreateValidation(_NamespaceNameValidation):
    """Validate create payloads for global roles."""

    display_name: str

    @field_validator("display_name")
    @classmethod
    def _validate_display_name(cls, value: str) -> str:
        return _validate_nonempty_trimmed(value, field_label="DisplayName")


class GlobalRoleUpdateValidation(IValidationBase):
    """Validate update payloads for global roles."""

    display_name: str | None = None

    @field_validator("display_name")
    @classmethod
    def _validate_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_nonempty_trimmed(value, field_label="DisplayName")


class RoleCreateValidation(_NamespaceNameValidation):
    """Validate create payloads for tenant roles."""

    tenant_id: uuid.UUID

    display_name: str

    @field_validator("display_name")
    @classmethod
    def _validate_display_name(cls, value: str) -> str:
        return _validate_nonempty_trimmed(value, field_label="DisplayName")


class RoleUpdateValidation(IValidationBase):
    """Validate update payloads for tenant roles."""

    display_name: str | None = None

    @field_validator("display_name")
    @classmethod
    def _validate_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_nonempty_trimmed(value, field_label="DisplayName")


class PermissionObjectCreateValidation(_NamespaceNameValidation):
    """Validate create payloads for permission objects."""


class PermissionTypeCreateValidation(_NamespaceNameValidation):
    """Validate create payloads for permission types."""


class GlobalPermissionEntryCreateValidation(IValidationBase):
    """Validate create payloads for global permission entries."""

    global_role_id: uuid.UUID

    permission_object_id: uuid.UUID

    permission_type_id: uuid.UUID

    permitted: bool


class GlobalPermissionEntryUpdateValidation(IValidationBase):
    """Validate update payloads for global permission entries."""

    permitted: bool | None = None


class PermissionEntryCreateValidation(IValidationBase):
    """Validate create payloads for tenant permission entries."""

    tenant_id: uuid.UUID

    role_id: uuid.UUID

    permission_object_id: uuid.UUID

    permission_type_id: uuid.UUID

    permitted: bool


class PermissionEntryUpdateValidation(IValidationBase):
    """Validate update payloads for tenant permission entries."""

    permitted: bool | None = None

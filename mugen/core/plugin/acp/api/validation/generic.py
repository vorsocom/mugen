"""Provides a base for Pydantic data validators."""

from pydantic import NonNegativeInt

from mugen.core.plugin.acp.api.validation.crud_builder import (
    build_create_validation_from_pascal,
    build_update_validation_from_pascal,
)
from mugen.core.plugin.acp.contract.api.validation import IValidationBase


class NoValidationSchema(IValidationBase):
    """No structural validation."""


class RowVersionValidation(IValidationBase):
    """Validate that RowVersion was provided."""

    row_version: NonNegativeInt


GlobalRoleMembershipCreateValidation = build_create_validation_from_pascal(
    "GlobalRoleMembershipCreateValidation",
    module=__name__,
    doc="Validate create payloads for GlobalRoleMembership.",
    required_fields=("GlobalRoleId", "UserId"),
)

RoleMembershipCreateValidation = build_create_validation_from_pascal(
    "RoleMembershipCreateValidation",
    module=__name__,
    doc="Validate create payloads for RoleMembership.",
    required_fields=("TenantId", "RoleId", "UserId"),
)

SystemFlagCreateValidation = build_create_validation_from_pascal(
    "SystemFlagCreateValidation",
    module=__name__,
    doc="Validate create payloads for SystemFlag.",
    required_fields=("Namespace", "Name"),
    optional_fields=("Description", "IsSet"),
)

SystemFlagUpdateValidation = build_update_validation_from_pascal(
    "SystemFlagUpdateValidation",
    module=__name__,
    doc="Validate update payloads for SystemFlag.",
    optional_fields=("Namespace", "Name", "Description", "IsSet"),
)

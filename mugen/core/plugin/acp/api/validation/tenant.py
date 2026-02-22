"""Provides Pydantic validators for ACP tenant-scoped CRUD payloads."""

__all__ = [
    "TenantDomainCreateValidation",
    "TenantDomainUpdateValidation",
    "TenantInvitationCreateValidation",
    "TenantInvitationUpdateValidation",
    "TenantMembershipCreateValidation",
    "TenantMembershipUpdateValidation",
]

from datetime import datetime
from typing import Literal
import uuid

from pydantic import EmailStr, field_validator

from mugen.core.plugin.acp.contract.api.validation import IValidationBase


class TenantDomainCreateValidation(IValidationBase):
    """Validate create payloads for tenant domains."""

    tenant_id: uuid.UUID

    domain: str

    is_primary: bool | None = None

    @field_validator("domain")
    @classmethod
    def _validate_domain_nonempty(cls, value: str) -> str:
        stripped = value.strip()
        if stripped == "":
            raise ValueError("Domain must be non-empty.")
        return stripped


class TenantDomainUpdateValidation(IValidationBase):
    """Validate update payloads for tenant domains."""

    domain: str | None = None

    is_primary: bool | None = None

    verified_at: datetime | None = None

    @field_validator("domain")
    @classmethod
    def _validate_domain_nonempty(cls, value: str | None) -> str | None:
        if value is None:
            return None

        stripped = value.strip()
        if stripped == "":
            raise ValueError("Domain must be non-empty.")
        return stripped


class TenantInvitationCreateValidation(IValidationBase):
    """Validate create payloads for tenant invitations."""

    tenant_id: uuid.UUID

    email: EmailStr


class TenantInvitationUpdateValidation(IValidationBase):
    """Validate update payloads for tenant invitations."""

    email: EmailStr | None = None


class TenantMembershipCreateValidation(IValidationBase):
    """Validate create payloads for tenant memberships."""

    tenant_id: uuid.UUID

    user_id: uuid.UUID

    role_in_tenant: Literal["owner", "admin", "member"] | None = None

    status: Literal["active", "invited", "suspended"] | None = None

    joined_at: datetime | None = None


class TenantMembershipUpdateValidation(IValidationBase):
    """Validate update payloads for tenant memberships."""

    role_in_tenant: Literal["owner", "admin", "member"] | None = None

    status: Literal["active", "invited", "suspended"] | None = None

    joined_at: datetime | None = None

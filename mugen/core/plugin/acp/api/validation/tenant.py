"""Provides Pydantic validators for ACP tenant-scoped CRUD payloads."""

__all__ = [
    "TenantCreateValidation",
    "TenantDomainCreateValidation",
    "TenantDomainUpdateValidation",
    "TenantInvitationCreateValidation",
    "TenantInvitationUpdateValidation",
    "TenantMembershipCreateValidation",
    "TenantMembershipUpdateValidation",
    "TenantUpdateValidation",
]

from datetime import datetime
from typing import Literal
import uuid

from pydantic import EmailStr, field_validator, model_validator

from mugen.core.plugin.acp.contract.api.validation import IValidationBase


class TenantCreateValidation(IValidationBase):
    """Validate create payloads for tenants."""

    name: str
    slug: str

    @field_validator("name", "slug")
    @classmethod
    def _validate_nonempty_text(cls, value: str, info) -> str:
        stripped = value.strip()
        if stripped == "":
            raise ValueError(f"{info.field_name.title()} must be non-empty.")
        return stripped


class TenantUpdateValidation(IValidationBase):
    """Validate update payloads for tenants."""

    name: str | None = None
    slug: str | None = None

    @model_validator(mode="after")
    def _validate_nonempty_patch(self) -> "TenantUpdateValidation":
        if not self.model_fields_set:
            raise ValueError("At least one mutable field must be provided.")
        return self

    @field_validator("name", "slug")
    @classmethod
    def _validate_optional_nonempty_text(cls, value: str | None, info) -> str | None:
        if value is None:
            return None

        stripped = value.strip()
        if stripped == "":
            raise ValueError(
                f"{info.field_name.title()} must be non-empty when provided."
            )
        return stripped


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

    @model_validator(mode="after")
    def _validate_nonempty_patch(self) -> "TenantDomainUpdateValidation":
        if not self.model_fields_set:
            raise ValueError("At least one mutable field must be provided.")
        return self

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

    @model_validator(mode="after")
    def _validate_nonempty_patch(self) -> "TenantInvitationUpdateValidation":
        if not self.model_fields_set:
            raise ValueError("At least one mutable field must be provided.")
        return self


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

    @model_validator(mode="after")
    def _validate_nonempty_patch(self) -> "TenantMembershipUpdateValidation":
        if not self.model_fields_set:
            raise ValueError("At least one mutable field must be provided.")
        return self

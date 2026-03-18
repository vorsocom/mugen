"""Validation models for ACP runtime profile CRUD payloads."""

from __future__ import annotations

__all__ = [
    "MessagingClientProfileCreateValidation",
    "MessagingClientProfileUpdateValidation",
    "RuntimeConfigProfileCreateValidation",
    "RuntimeConfigProfileUpdateValidation",
]

from typing import Any
import uuid

from pydantic import model_validator

from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.service.messaging_client_profile import (
    MessagingClientProfileService,
)
from mugen.core.plugin.acp.service.runtime_config_profile import (
    RuntimeConfigProfileService,
)
from mugen.core.plugin.acp.utility.runtime_config_policy import (
    normalize_runtime_config_category,
    normalize_runtime_config_profile_key,
    normalize_runtime_config_settings,
)

_CLIENT_PROFILE_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "line": ("path_token",),
    "matrix": ("recipient_user_id",),
    "signal": ("account_number",),
    "telegram": ("path_token",),
    "wechat": ("path_token", "provider"),
    "whatsapp": ("path_token", "phone_number_id"),
}

_IDENTIFIER_FIELDS = (
    "path_token",
    "recipient_user_id",
    "account_number",
    "phone_number_id",
    "provider",
)


class RuntimeConfigProfileCreateValidation(IValidationBase):
    """Validate create payloads for runtime config profiles."""

    tenant_id: uuid.UUID | None = None
    category: str
    profile_key: str
    display_name: str | None = None
    is_active: bool | None = None
    settings_json: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "RuntimeConfigProfileCreateValidation":
        try:
            self.category = normalize_runtime_config_category(self.category)
            self.profile_key = normalize_runtime_config_profile_key(
                category=self.category,
                value=self.profile_key,
            )
            if self.display_name is not None:
                self.display_name = str(self.display_name).strip()
            self.settings_json = normalize_runtime_config_settings(
                category=self.category,
                profile_key=self.profile_key,
                value=self.settings_json,
            )
            self.attributes = RuntimeConfigProfileService._normalize_attributes(
                self.attributes
            )
        except RuntimeError as exc:
            raise ValueError(str(exc)) from exc
        return self


class RuntimeConfigProfileUpdateValidation(IValidationBase):
    """Validate update payloads for runtime config profiles."""

    category: str | None = None
    profile_key: str | None = None
    display_name: str | None = None
    is_active: bool | None = None
    settings_json: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "RuntimeConfigProfileUpdateValidation":
        try:
            if not self.model_fields_set:
                raise ValueError("At least one mutable field must be provided.")

            if self.category is not None:
                self.category = normalize_runtime_config_category(self.category)
            if self.profile_key is not None:
                normalized = str(self.profile_key).strip()
                if normalized == "":
                    raise ValueError("ProfileKey must be non-empty when provided.")
                self.profile_key = normalized
            if self.display_name is not None:
                self.display_name = str(self.display_name).strip()
            if (
                self.category is not None
                and self.profile_key is not None
                and "settings_json" in self.model_fields_set
            ):
                self.profile_key = normalize_runtime_config_profile_key(
                    category=self.category,
                    value=self.profile_key,
                )
                self.settings_json = normalize_runtime_config_settings(
                    category=self.category,
                    profile_key=self.profile_key,
                    value=self.settings_json,
                )
            self.attributes = RuntimeConfigProfileService._normalize_attributes(
                self.attributes
            )
        except RuntimeError as exc:
            raise ValueError(str(exc)) from exc
        return self


class MessagingClientProfileCreateValidation(IValidationBase):
    """Validate create payloads for messaging client profiles."""

    tenant_id: uuid.UUID | None = None
    platform_key: str
    profile_key: str
    display_name: str | None = None
    is_active: bool | None = None
    settings: dict[str, Any] | None = None
    secret_refs: dict[str, str] | None = None
    path_token: str | None = None
    recipient_user_id: str | None = None
    account_number: str | None = None
    phone_number_id: str | None = None
    provider: str | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "MessagingClientProfileCreateValidation":
        try:
            self.platform_key = MessagingClientProfileService._normalize_platform_key(
                self.platform_key
            )
            self.profile_key = MessagingClientProfileService._normalize_required_text(
                self.profile_key,
                field_name="ProfileKey",
            )
            self.display_name = (
                MessagingClientProfileService._normalize_optional_text(
                    self.display_name
                )
            )
            self.settings = MessagingClientProfileService._normalize_settings(
                platform_key=self.platform_key,
                value=self.settings,
                is_active=bool(self.is_active if self.is_active is not None else True),
            )
            self.secret_refs = (
                MessagingClientProfileService._normalize_platform_secret_refs(
                    platform_key=self.platform_key,
                    value=self.secret_refs,
                )
            )
            for field_name in _IDENTIFIER_FIELDS:
                value = getattr(self, field_name)
                setattr(
                    self,
                    field_name,
                    MessagingClientProfileService._normalize_optional_text(value),
                )
            for field_name in _CLIENT_PROFILE_REQUIRED_FIELDS.get(
                self.platform_key,
                (),
            ):
                if getattr(self, field_name) is None:
                    raise ValueError(
                        f"{field_name} is required for platform {self.platform_key!r}."
                    )
            return self
        except RuntimeError as exc:
            raise ValueError(str(exc)) from exc


class MessagingClientProfileUpdateValidation(IValidationBase):
    """Validate update payloads for messaging client profiles."""

    platform_key: str | None = None
    profile_key: str | None = None
    display_name: str | None = None
    is_active: bool | None = None
    settings: dict[str, Any] | None = None
    secret_refs: dict[str, str] | None = None
    path_token: str | None = None
    recipient_user_id: str | None = None
    account_number: str | None = None
    phone_number_id: str | None = None
    provider: str | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "MessagingClientProfileUpdateValidation":
        try:
            if not self.model_fields_set:
                raise ValueError("At least one mutable field must be provided.")

            if self.platform_key is not None:
                self.platform_key = (
                    MessagingClientProfileService._normalize_platform_key(
                        self.platform_key
                    )
                )
            if self.profile_key is not None:
                self.profile_key = (
                    MessagingClientProfileService._normalize_required_text(
                        self.profile_key,
                        field_name="ProfileKey",
                    )
                )
            if self.display_name is not None:
                self.display_name = str(self.display_name).strip()
            if self.platform_key is not None and "settings" in self.model_fields_set:
                self.settings = MessagingClientProfileService._normalize_settings(
                    platform_key=self.platform_key,
                    value=self.settings,
                    is_active=bool(
                        self.is_active if self.is_active is not None else True
                    ),
                )
            if (
                self.platform_key is not None
                and "secret_refs" in self.model_fields_set
            ):
                self.secret_refs = (
                    MessagingClientProfileService._normalize_platform_secret_refs(
                        platform_key=self.platform_key,
                        value=self.secret_refs,
                    )
                )
            for field_name in _IDENTIFIER_FIELDS:
                if field_name not in self.model_fields_set:
                    continue
                value = getattr(self, field_name)
                if value is None:
                    continue
                setattr(self, field_name, str(value).strip())
            return self
        except RuntimeError as exc:
            raise ValueError(str(exc)) from exc

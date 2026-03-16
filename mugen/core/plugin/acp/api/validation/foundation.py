"""Validation models for ACP Phase 1 foundation actions."""

from __future__ import annotations

from datetime import datetime
import uuid
from typing import Any

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator

from mugen.core.plugin.acp.contract.api.validation import IValidationBase


class DedupAcquireValidation(IValidationBase):
    """Validate payload for dedup acquire actions."""

    tenant_id: uuid.UUID | None = None
    scope: str
    idempotency_key: str
    request_hash: str | None = None
    owner_instance: str | None = None
    ttl_seconds: PositiveInt | None = None
    lease_seconds: PositiveInt | None = None

    @model_validator(mode="after")
    def _validate_required_text(self) -> "DedupAcquireValidation":
        if not self.scope.strip():
            raise ValueError("Scope must be non-empty.")
        if not self.idempotency_key.strip():
            raise ValueError("IdempotencyKey must be non-empty.")
        return self


class DedupRecordCreateValidation(IValidationBase):
    """Validate create payloads for dedup records."""

    scope: str
    idempotency_key: str
    request_hash: str | None = None
    status: str | None = None
    result_ref: str | None = None
    response_code: int | None = Field(default=None, ge=100, le=599)
    response_payload: Any | None = None
    error_code: str | None = None
    error_message: str | None = None
    owner_instance: str | None = None
    lease_expires_at: datetime | None = None
    expires_at: datetime

    @model_validator(mode="after")
    def _validate_required_text(self) -> "DedupRecordCreateValidation":
        self.scope = self.scope.strip()
        if self.scope == "":
            raise ValueError("Scope must be non-empty.")

        self.idempotency_key = self.idempotency_key.strip()
        if self.idempotency_key == "":
            raise ValueError("IdempotencyKey must be non-empty.")

        if self.status is not None:
            self.status = self.status.strip().lower()
            if self.status not in {"in_progress", "succeeded", "failed"}:
                raise ValueError(
                    "Status must be one of in_progress, succeeded, or failed."
                )
        return self


class DedupCommitSuccessValidation(IValidationBase):
    """Validate payload for dedup commit_success actions."""

    response_code: int = Field(default=200, ge=100, le=599)
    response_payload: Any | None = None
    result_ref: str | None = None
    ttl_seconds: PositiveInt | None = None


class DedupCommitFailureValidation(IValidationBase):
    """Validate payload for dedup commit_failure actions."""

    response_code: int = Field(default=500, ge=100, le=599)
    response_payload: Any | None = None
    error_code: str | None = None
    error_message: str | None = None
    ttl_seconds: PositiveInt | None = None


class DedupSweepExpiredValidation(IValidationBase):
    """Validate payload for dedup sweep_expired actions."""

    batch_size: PositiveInt | None = None


class _SchemaReferenceValidation(IValidationBase):
    """Base model for schema-reference action payloads."""

    tenant_id: uuid.UUID | None = None
    schema_definition_id: uuid.UUID | None = None
    key: str | None = None
    version: PositiveInt | None = None

    @model_validator(mode="after")
    def _validate_reference(self) -> "_SchemaReferenceValidation":
        if self.schema_definition_id is not None:
            return self

        key = (self.key or "").strip()
        if key == "":
            raise ValueError("Provide SchemaDefinitionId or Key + Version.")

        if self.version is None:
            raise ValueError("Version is required when SchemaDefinitionId is omitted.")

        self.key = key
        return self


class SchemaDefinitionCreateValidation(IValidationBase):
    """Validate create payloads for schema definitions."""

    key: str
    version: PositiveInt
    title: str | None = None
    description: str | None = None
    schema_kind: str = "json_schema"
    schema_payload: dict[str, Any] = Field(alias="SchemaJson")
    status: str | None = None
    activated_at: datetime | None = None
    activated_by_user_id: uuid.UUID | None = None
    checksum_sha256: str | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "SchemaDefinitionCreateValidation":
        self.key = self.key.strip()
        if self.key == "":
            raise ValueError("Key must be non-empty.")

        self.schema_kind = self.schema_kind.strip()
        if self.schema_kind == "":
            self.schema_kind = "json_schema"

        if self.status is not None:
            self.status = self.status.strip().lower()
            if self.status not in {"draft", "active", "inactive"}:
                raise ValueError("Status must be one of draft, active, or inactive.")

        return self


class SchemaDefinitionUpdateValidation(IValidationBase):
    """Validate update payloads for schema definitions."""

    title: str | None = None
    description: str | None = None
    schema_kind: str | None = None
    status: str | None = None
    activated_at: datetime | None = None
    activated_by_user_id: uuid.UUID | None = None
    checksum_sha256: str | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "SchemaDefinitionUpdateValidation":
        if self.schema_kind is not None:
            self.schema_kind = self.schema_kind.strip()
            if self.schema_kind == "":
                raise ValueError("SchemaKind must be non-empty when provided.")

        if self.status is not None:
            self.status = self.status.strip().lower()
            if self.status not in {"draft", "active", "inactive"}:
                raise ValueError("Status must be one of draft, active, or inactive.")

        return self


class SchemaBindingCreateValidation(IValidationBase):
    """Validate create payloads for schema bindings."""

    schema_definition_id: uuid.UUID
    target_namespace: str
    target_entity_set: str
    target_action: str | None = None
    binding_kind: str
    is_required: bool = True
    is_active: bool = True
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "SchemaBindingCreateValidation":
        self.target_namespace = self.target_namespace.strip()
        if self.target_namespace == "":
            raise ValueError("TargetNamespace must be non-empty.")

        self.target_entity_set = self.target_entity_set.strip()
        if self.target_entity_set == "":
            raise ValueError("TargetEntitySet must be non-empty.")

        if self.target_action is not None:
            self.target_action = self.target_action.strip() or None

        self.binding_kind = self.binding_kind.strip().lower()
        if self.binding_kind == "":
            raise ValueError("BindingKind must be non-empty.")

        return self


class SchemaBindingUpdateValidation(IValidationBase):
    """Validate update payloads for schema bindings."""

    target_action: str | None = None
    is_required: bool | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "SchemaBindingUpdateValidation":
        if self.target_action is not None:
            self.target_action = self.target_action.strip() or None
        return self


class SchemaValidateValidation(_SchemaReferenceValidation):
    """Validate payload for schema validate actions."""

    payload: Any


class SchemaCoerceValidation(_SchemaReferenceValidation):
    """Validate payload for schema coerce actions."""

    payload: Any


class SchemaActivateVersionValidation(IValidationBase):
    """Validate payload for schema activate_version actions."""

    tenant_id: uuid.UUID | None = None
    key: str
    version: PositiveInt

    @model_validator(mode="after")
    def _validate_key(self) -> "SchemaActivateVersionValidation":
        self.key = self.key.strip()
        if self.key == "":
            raise ValueError("Key must be non-empty.")
        return self


class KeyRefCreateValidation(IValidationBase):
    """Validate create payloads for key references."""

    tenant_id: uuid.UUID | None = None
    purpose: str
    key_id: str
    provider: str = "local"
    status: str | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "KeyRefCreateValidation":
        self.purpose = self.purpose.strip()
        if self.purpose == "":
            raise ValueError("Purpose must be non-empty.")

        self.key_id = self.key_id.strip()
        if self.key_id == "":
            raise ValueError("KeyId must be non-empty.")

        self.provider = (self.provider or "local").strip()
        if self.provider == "":
            self.provider = "local"

        if self.status is not None:
            self.status = self.status.strip().lower()
            if self.status not in {"active", "retired", "destroyed"}:
                raise ValueError("Status must be one of active, retired, or destroyed.")

        return self


class KeyRefRotateValidation(IValidationBase):
    """Validate payload for key rotation."""

    tenant_id: uuid.UUID | None = None
    purpose: str
    key_id: str
    provider: str = "local"
    secret_value: str | None = Field(default=None, exclude=True, repr=False)
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "KeyRefRotateValidation":
        self.purpose = self.purpose.strip()
        if self.purpose == "":
            raise ValueError("Purpose must be non-empty.")

        self.key_id = self.key_id.strip()
        if self.key_id == "":
            raise ValueError("KeyId must be non-empty.")

        self.provider = (self.provider or "local").strip()
        if self.provider == "":
            self.provider = "local"
        if self.secret_value is not None:
            self.secret_value = self.secret_value
        return self


class KeyRefLifecycleValidation(IValidationBase):
    """Validate payload for retire/destroy key lifecycle actions."""

    row_version: NonNegativeInt
    reason: str | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "KeyRefLifecycleValidation":
        if self.reason is not None:
            self.reason = self.reason.strip()
            if self.reason == "":
                raise ValueError("Reason cannot be empty if provided.")
        return self


class PluginCapabilityGrantCreateValidation(IValidationBase):
    """Validate create payloads for plugin capability grants."""

    tenant_id: uuid.UUID | None = None
    plugin_key: str
    capabilities: list[str]
    expires_at: datetime | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "PluginCapabilityGrantCreateValidation":
        self.plugin_key = self.plugin_key.strip()
        if self.plugin_key == "":
            raise ValueError("PluginKey must be non-empty.")

        cleaned: list[str] = []
        seen: set[str] = set()
        for item in self.capabilities:
            capability = str(item).strip().lower()
            if capability == "" or capability in seen:
                continue
            seen.add(capability)
            cleaned.append(capability)

        if not cleaned:
            raise ValueError("Capabilities must include at least one value.")

        self.capabilities = cleaned
        return self


class PluginCapabilityGrantGrantValidation(PluginCapabilityGrantCreateValidation):
    """Validate payload for capability grant actions."""


class PluginCapabilityGrantRevokeValidation(IValidationBase):
    """Validate payload for capability grant revoke action."""

    row_version: NonNegativeInt
    reason: str | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "PluginCapabilityGrantRevokeValidation":
        if self.reason is not None:
            self.reason = self.reason.strip()
            if self.reason == "":
                raise ValueError("Reason cannot be empty if provided.")
        return self

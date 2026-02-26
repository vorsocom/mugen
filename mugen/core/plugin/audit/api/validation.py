"""Validation schemas used by audit ACP actions."""

from __future__ import annotations

from datetime import datetime
import uuid
from typing import Any, Literal

from pydantic import NonNegativeInt, PositiveInt, model_validator

from mugen.core.plugin.acp.contract.api.validation import IValidationBase


class AuditEventLifecycleActionValidation(IValidationBase):
    """Base validator for row-versioned audit lifecycle entity actions."""

    row_version: NonNegativeInt
    reason: str

    @model_validator(mode="after")
    def _validate_reason(self) -> "AuditEventLifecycleActionValidation":
        if not (self.reason or "").strip():
            raise ValueError("Reason must be non-empty.")
        return self


class AuditEventPlaceLegalHoldValidation(AuditEventLifecycleActionValidation):
    """Validate payload for place_legal_hold actions."""

    legal_hold_until: datetime | None = None


class AuditEventReleaseLegalHoldValidation(AuditEventLifecycleActionValidation):
    """Validate payload for release_legal_hold actions."""


class AuditEventRedactValidation(AuditEventLifecycleActionValidation):
    """Validate payload for redact actions."""


class AuditEventTombstoneValidation(AuditEventLifecycleActionValidation):
    """Validate payload for tombstone actions."""

    purge_after_days: NonNegativeInt | None = None


class AuditEventRunLifecycleValidation(IValidationBase):
    """Validate payload for run_lifecycle action."""

    batch_size: PositiveInt | None = None
    max_batches: PositiveInt | None = None
    dry_run: bool = False
    now_override: datetime | None = None
    phases: (
        list[
            Literal[
                "seal_backlog",
                "redact_due",
                "tombstone_expired",
                "purge_due",
            ]
        ]
        | None
    ) = None


class AuditEventVerifyChainValidation(IValidationBase):
    """Validate payload for verify_chain action."""

    from_occurred_at: datetime | None = None
    to_occurred_at: datetime | None = None
    max_rows: PositiveInt | None = None
    require_clean: bool = False


class AuditEventSealBacklogValidation(IValidationBase):
    """Validate payload for seal_backlog action."""

    batch_size: PositiveInt | None = None
    max_batches: PositiveInt | None = None


class AuditCorrelationResolveTraceValidation(IValidationBase):
    """Validate payload for resolve_trace actions."""

    tenant_id: uuid.UUID | None = None
    trace_id: str | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    max_rows: PositiveInt | None = None

    @model_validator(mode="after")
    def _validate_reference(self) -> "AuditCorrelationResolveTraceValidation":
        trace = (self.trace_id or "").strip()
        correlation = (self.correlation_id or "").strip()
        request = (self.request_id or "").strip()

        if trace == "" and correlation == "" and request == "":
            raise ValueError("Provide TraceId, CorrelationId, or RequestId.")

        self.trace_id = trace or None
        self.correlation_id = correlation or None
        self.request_id = request or None
        return self


class AuditBizTraceInspectTraceValidation(IValidationBase):
    """Validate payload for inspect_trace actions."""

    tenant_id: uuid.UUID | None = None
    trace_id: str | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    stage: str | None = None
    max_rows: PositiveInt | None = None

    @model_validator(mode="after")
    def _validate_reference(self) -> "AuditBizTraceInspectTraceValidation":
        trace = (self.trace_id or "").strip()
        correlation = (self.correlation_id or "").strip()
        request = (self.request_id or "").strip()
        stage = (self.stage or "").strip()

        if trace == "" and correlation == "" and request == "":
            raise ValueError("Provide TraceId, CorrelationId, or RequestId.")

        self.trace_id = trace or None
        self.correlation_id = correlation or None
        self.request_id = request or None
        self.stage = stage or None
        return self


class EvidenceBlobRegisterValidation(IValidationBase):
    """Validate payload for evidence register actions."""

    tenant_id: uuid.UUID | None = None
    trace_id: str | None = None
    source_plugin: str | None = None
    subject_namespace: str | None = None
    subject_id: uuid.UUID | None = None
    storage_uri: str
    content_hash: str
    hash_alg: str = "sha256"
    content_length: NonNegativeInt | None = None
    immutability: str = "immutable"
    retention_until: datetime | None = None
    redaction_due_at: datetime | None = None
    meta: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "EvidenceBlobRegisterValidation":
        self.storage_uri = self.storage_uri.strip()
        if self.storage_uri == "":
            raise ValueError("StorageUri must be non-empty.")

        self.content_hash = self.content_hash.strip()
        if self.content_hash == "":
            raise ValueError("ContentHash must be non-empty.")

        self.hash_alg = (self.hash_alg or "sha256").strip().lower()
        if self.hash_alg == "":
            self.hash_alg = "sha256"

        self.immutability = (self.immutability or "immutable").strip().lower()
        if self.immutability not in {"immutable", "mutable"}:
            raise ValueError("Immutability must be immutable or mutable.")

        if self.trace_id is not None and not self.trace_id.strip():
            raise ValueError("TraceId cannot be empty if provided.")
        if self.source_plugin is not None and not self.source_plugin.strip():
            raise ValueError("SourcePlugin cannot be empty if provided.")
        if self.subject_namespace is not None and not self.subject_namespace.strip():
            raise ValueError("SubjectNamespace cannot be empty if provided.")

        return self


class EvidenceBlobVerifyHashValidation(IValidationBase):
    """Validate payload for evidence hash verification actions."""

    row_version: NonNegativeInt
    observed_hash: str
    observed_hash_alg: str = "sha256"

    @model_validator(mode="after")
    def _validate_payload(self) -> "EvidenceBlobVerifyHashValidation":
        self.observed_hash = self.observed_hash.strip()
        if self.observed_hash == "":
            raise ValueError("ObservedHash must be non-empty.")
        self.observed_hash_alg = (self.observed_hash_alg or "sha256").strip().lower()
        if self.observed_hash_alg == "":
            self.observed_hash_alg = "sha256"
        return self


class EvidenceBlobLifecycleActionValidation(IValidationBase):
    """Base validator for row-versioned evidence lifecycle entity actions."""

    row_version: NonNegativeInt
    reason: str

    @model_validator(mode="after")
    def _validate_reason(self) -> "EvidenceBlobLifecycleActionValidation":
        if not (self.reason or "").strip():
            raise ValueError("Reason must be non-empty.")
        return self


class EvidenceBlobPlaceLegalHoldValidation(EvidenceBlobLifecycleActionValidation):
    """Validate payload for place_legal_hold actions."""

    legal_hold_until: datetime | None = None


class EvidenceBlobReleaseLegalHoldValidation(EvidenceBlobLifecycleActionValidation):
    """Validate payload for release_legal_hold actions."""


class EvidenceBlobRedactValidation(EvidenceBlobLifecycleActionValidation):
    """Validate payload for redact actions."""


class EvidenceBlobTombstoneValidation(EvidenceBlobLifecycleActionValidation):
    """Validate payload for tombstone actions."""

    purge_after_days: NonNegativeInt | None = None


class EvidenceBlobPurgeValidation(EvidenceBlobLifecycleActionValidation):
    """Validate payload for purge actions."""

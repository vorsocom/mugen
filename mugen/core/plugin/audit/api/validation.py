"""Validation schemas used by audit ACP actions."""

from __future__ import annotations

from datetime import datetime
import uuid
from typing import Literal

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

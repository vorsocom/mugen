"""Validation schemas used by ops_sla ACP actions and create payloads."""

from datetime import datetime
from typing import Any, Literal
import uuid

from pydantic import NonNegativeInt, PositiveInt, model_validator

from mugen.core.plugin.acp.contract.api.validation import IValidationBase


class SlaClockCreateValidation(IValidationBase):
    """Validate generic create inputs for SlaClock."""

    tenant_id: uuid.UUID

    tracked_namespace: str
    metric: str

    tracked_id: uuid.UUID | None = None
    tracked_ref: str | None = None

    policy_id: uuid.UUID | None = None
    calendar_id: uuid.UUID | None = None
    target_id: uuid.UUID | None = None
    clock_definition_id: uuid.UUID | None = None
    trace_id: str | None = None

    priority: str | None = None
    severity: str | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_tracking_target(self) -> "SlaClockCreateValidation":
        if not (self.tracked_namespace or "").strip():
            raise ValueError("TrackedNamespace must be non-empty.")

        if not (self.metric or "").strip():
            raise ValueError("Metric must be non-empty.")

        tracked_ref = (self.tracked_ref or "").strip()
        if self.tracked_ref is not None and not tracked_ref:
            raise ValueError("TrackedRef cannot be empty if provided.")

        if self.tracked_id is None and not tracked_ref:
            raise ValueError("Provide TrackedId or TrackedRef.")

        if self.trace_id is not None and not self.trace_id.strip():
            raise ValueError("TraceId cannot be empty if provided.")

        return self


class SlaClockActionValidation(IValidationBase):
    """Base validator for clock actions that require RowVersion."""

    row_version: NonNegativeInt

    note: str | None = None


class SlaClockStartValidation(SlaClockActionValidation):
    """Validate payload for start_clock actions."""


class SlaClockPauseValidation(SlaClockActionValidation):
    """Validate payload for pause_clock actions."""


class SlaClockResumeValidation(SlaClockActionValidation):
    """Validate payload for resume_clock actions."""


class SlaClockStopValidation(SlaClockActionValidation):
    """Validate payload for stop_clock actions."""


class SlaClockMarkBreachedValidation(SlaClockActionValidation):
    """Validate payload for mark_breached actions."""

    event_type: Literal["breached", "escalated", "acknowledged"] = "breached"
    escalation_level: NonNegativeInt | None = None
    reason: str | None = None
    payload: dict[str, Any] | None = None


class SlaClockTickValidation(IValidationBase):
    """Validate payload for tick actions."""

    batch_size: PositiveInt | None = None
    now_utc: datetime | None = None
    dry_run: bool = False


class SlaEscalationEvaluateValidation(IValidationBase):
    """Validate payload for escalation evaluate actions."""

    policy_key: str | None = None
    trigger_event_json: dict[str, Any]

    @model_validator(mode="after")
    def _validate_payload(self) -> "SlaEscalationEvaluateValidation":
        if self.policy_key is not None and not self.policy_key.strip():
            raise ValueError("PolicyKey cannot be empty if provided.")
        if not isinstance(self.trigger_event_json, dict):
            raise ValueError("TriggerEventJson must be an object.")
        return self


class SlaEscalationExecuteValidation(SlaEscalationEvaluateValidation):
    """Validate payload for escalation execute actions."""

    dry_run: bool = False


class SlaEscalationTestValidation(IValidationBase):
    """Validate payload for escalation test actions."""

    policy_key: str
    sample_event_json: dict[str, Any]

    @model_validator(mode="after")
    def _validate_payload(self) -> "SlaEscalationTestValidation":
        if not (self.policy_key or "").strip():
            raise ValueError("PolicyKey must be non-empty.")
        if not isinstance(self.sample_event_json, dict):
            raise ValueError("SampleEventJson must be an object.")
        return self


class SlaTargetCreateValidation(IValidationBase):
    """Validate generic create inputs for SlaTarget."""

    tenant_id: uuid.UUID

    policy_id: uuid.UUID
    metric: str
    target_minutes: PositiveInt

    priority: str | None = None
    severity: str | None = None

    warn_before_minutes: NonNegativeInt | None = None
    auto_breach: bool | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_strings(self) -> "SlaTargetCreateValidation":
        if not (self.metric or "").strip():
            raise ValueError("Metric must be non-empty.")

        if self.priority is not None and not (self.priority or "").strip():
            raise ValueError("Priority cannot be empty if provided.")

        if self.severity is not None and not (self.severity or "").strip():
            raise ValueError("Severity cannot be empty if provided.")

        return self

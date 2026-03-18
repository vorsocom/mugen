"""Validation schemas used by ops_sla ACP actions and create payloads."""

from datetime import datetime
from typing import Any, Literal
import uuid

from pydantic import NonNegativeInt, PositiveInt, model_validator

from mugen.core.plugin.acp.api.validation.crud_builder import (
    build_create_validation_from_pascal,
    build_update_validation_from_pascal,
)
from mugen.core.plugin.acp.contract.api.validation import IValidationBase

SlaPolicyCreateValidation = build_create_validation_from_pascal(
    "SlaPolicyCreateValidation",
    module=__name__,
    doc="Validate create payloads for SlaPolicy.",
    required_fields=("TenantId", "Code", "Name"),
)

SlaPolicyUpdateValidation = build_update_validation_from_pascal(
    "SlaPolicyUpdateValidation",
    module=__name__,
    doc="Validate update payloads for SlaPolicy.",
    optional_fields=(
        "Code",
        "Name",
        "Description",
        "CalendarId",
        "IsActive",
        "Attributes",
    ),
)

SlaCalendarCreateValidation = build_create_validation_from_pascal(
    "SlaCalendarCreateValidation",
    module=__name__,
    doc="Validate create payloads for SlaCalendar.",
    required_fields=("TenantId", "Code", "Name", "Timezone"),
)

SlaCalendarUpdateValidation = build_update_validation_from_pascal(
    "SlaCalendarUpdateValidation",
    module=__name__,
    doc="Validate update payloads for SlaCalendar.",
    optional_fields=(
        "Code",
        "Name",
        "Timezone",
        "BusinessStartTime",
        "BusinessEndTime",
        "BusinessDays",
        "HolidayRefs",
        "IsActive",
        "Attributes",
    ),
)


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


SlaTargetUpdateValidation = build_update_validation_from_pascal(
    "SlaTargetUpdateValidation",
    module=__name__,
    doc="Validate update payloads for SlaTarget.",
    optional_fields=(
        "Metric",
        "Priority",
        "Severity",
        "TargetMinutes",
        "WarnBeforeMinutes",
        "AutoBreach",
        "Attributes",
    ),
)

SlaClockUpdateValidation = build_update_validation_from_pascal(
    "SlaClockUpdateValidation",
    module=__name__,
    doc="Validate update payloads for SlaClock.",
    optional_fields=(
        "PolicyId",
        "CalendarId",
        "TargetId",
        "ClockDefinitionId",
        "TraceId",
        "TrackedNamespace",
        "TrackedId",
        "TrackedRef",
        "Metric",
        "Priority",
        "Severity",
        "WarnedOffsetsJson",
        "Attributes",
    ),
)

SlaClockDefinitionCreateValidation = build_create_validation_from_pascal(
    "SlaClockDefinitionCreateValidation",
    module=__name__,
    doc="Validate create payloads for SlaClockDefinition.",
    required_fields=("TenantId", "Code", "Name", "Metric", "TargetMinutes"),
)

SlaClockDefinitionUpdateValidation = build_update_validation_from_pascal(
    "SlaClockDefinitionUpdateValidation",
    module=__name__,
    doc="Validate update payloads for SlaClockDefinition.",
    optional_fields=(
        "Code",
        "Name",
        "Description",
        "Metric",
        "TargetMinutes",
        "WarnOffsetsJson",
        "IsActive",
        "Attributes",
    ),
)

SlaEscalationPolicyCreateValidation = build_create_validation_from_pascal(
    "SlaEscalationPolicyCreateValidation",
    module=__name__,
    doc="Validate create payloads for SlaEscalationPolicy.",
    required_fields=("TenantId", "PolicyKey", "Name"),
)

SlaEscalationPolicyUpdateValidation = build_update_validation_from_pascal(
    "SlaEscalationPolicyUpdateValidation",
    module=__name__,
    doc="Validate update payloads for SlaEscalationPolicy.",
    optional_fields=(
        "PolicyKey",
        "Name",
        "Description",
        "Priority",
        "TriggersJson",
        "ActionsJson",
        "IsActive",
        "Attributes",
    ),
)

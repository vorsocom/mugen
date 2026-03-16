"""Validation schemas used by ops_metering ACP actions and create payloads."""

from datetime import datetime
from typing import Any
import uuid

from pydantic import NonNegativeInt, PositiveInt, model_validator

from mugen.core.plugin.acp.contract.api.validation import IValidationBase


class UsageSessionCreateValidation(IValidationBase):
    """Validate generic create inputs for UsageSession."""

    tenant_id: uuid.UUID
    meter_definition_id: uuid.UUID

    meter_policy_id: uuid.UUID | None = None

    tracked_namespace: str
    tracked_id: uuid.UUID | None = None
    tracked_ref: str | None = None

    account_id: uuid.UUID | None = None
    subscription_id: uuid.UUID | None = None
    price_id: uuid.UUID | None = None

    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_tracking_target(self) -> "UsageSessionCreateValidation":
        if not (self.tracked_namespace or "").strip():
            raise ValueError("TrackedNamespace must be non-empty.")

        tracked_ref = (self.tracked_ref or "").strip()
        if self.tracked_ref is not None and not tracked_ref:
            raise ValueError("TrackedRef cannot be empty if provided.")

        if self.tracked_id is None and not tracked_ref:
            raise ValueError("Provide TrackedId or TrackedRef.")

        return self


class UsageRecordCreateValidation(IValidationBase):
    """Validate generic create inputs for UsageRecord."""

    tenant_id: uuid.UUID
    meter_definition_id: uuid.UUID

    meter_policy_id: uuid.UUID | None = None
    usage_session_id: uuid.UUID | None = None

    account_id: uuid.UUID | None = None
    subscription_id: uuid.UUID | None = None
    price_id: uuid.UUID | None = None

    occurred_at: datetime | None = None

    measured_minutes: NonNegativeInt = 0
    measured_units: NonNegativeInt = 0
    measured_tasks: NonNegativeInt = 0

    idempotency_key: str | None = None
    external_ref: str | None = None

    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_measures(self) -> "UsageRecordCreateValidation":
        if (
            int(self.measured_minutes) <= 0
            and int(self.measured_units) <= 0
            and int(self.measured_tasks) <= 0
        ):
            raise ValueError(
                "Provide at least one positive value in"
                " MeasuredMinutes/MeasuredUnits/MeasuredTasks."
            )

        if self.idempotency_key is not None and not self.idempotency_key.strip():
            raise ValueError("IdempotencyKey cannot be empty if provided.")

        if self.external_ref is not None and not self.external_ref.strip():
            raise ValueError("ExternalRef cannot be empty if provided.")

        return self


class UsageSessionActionValidation(IValidationBase):
    """Base validator for usage session actions that require RowVersion."""

    row_version: NonNegativeInt

    note: str | None = None


class UsageSessionStartValidation(UsageSessionActionValidation):
    """Validate payload for start_session actions."""


class UsageSessionPauseValidation(UsageSessionActionValidation):
    """Validate payload for pause_session actions."""


class UsageSessionResumeValidation(UsageSessionActionValidation):
    """Validate payload for resume_session actions."""


class UsageSessionStopValidation(UsageSessionActionValidation):
    """Validate payload for stop_session actions."""


class UsageRecordRateValidation(IValidationBase):
    """Validate payload for rate_record actions."""

    row_version: NonNegativeInt

    note: str | None = None


class UsageRecordVoidValidation(IValidationBase):
    """Validate payload for void_record actions."""

    row_version: NonNegativeInt

    reason: str | None = None
    note: str | None = None


class MeterPolicyCreateValidation(IValidationBase):
    """Validate generic create inputs for MeterPolicy."""

    tenant_id: uuid.UUID
    meter_definition_id: uuid.UUID

    code: str
    name: str

    description: str | None = None

    cap_minutes: NonNegativeInt | None = None
    cap_units: NonNegativeInt | None = None
    cap_tasks: NonNegativeInt | None = None

    multiplier_bps: NonNegativeInt = 10000
    rounding_mode: str | None = None
    rounding_step: PositiveInt = 1

    billable_window_minutes: NonNegativeInt | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None

    is_active: bool | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_strings(self) -> "MeterPolicyCreateValidation":
        if not (self.code or "").strip():
            raise ValueError("Code must be non-empty.")

        if not (self.name or "").strip():
            raise ValueError("Name must be non-empty.")

        if self.description is not None and not (self.description or "").strip():
            raise ValueError("Description cannot be empty if provided.")

        if self.effective_to is not None and self.effective_from is not None:
            if self.effective_to < self.effective_from:
                raise ValueError("EffectiveTo must be >= EffectiveFrom.")

        return self

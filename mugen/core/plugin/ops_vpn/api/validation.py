"""Validation schemas used by ops_vpn ACP actions."""

from datetime import datetime
from typing import Any
import uuid

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator

from mugen.core.plugin.acp.contract.api.validation import IValidationBase


class VendorScorecardRollupValidation(IValidationBase):
    """Validate inputs for scorecard rollup actions."""

    vendor_id: uuid.UUID
    period_start: datetime
    period_end: datetime

    @model_validator(mode="after")
    def _validate_period(self) -> "VendorScorecardRollupValidation":
        if self.period_end < self.period_start:
            raise ValueError("PeriodEnd must be greater than or equal to PeriodStart.")
        return self


class VendorPerformanceEventCreateValidation(IValidationBase):
    """Validate generic create inputs for VendorPerformanceEvent."""

    vendor_id: uuid.UUID
    metric_type: str

    observed_at: datetime | None = None
    metric_value: NonNegativeInt | None = None
    metric_numerator: NonNegativeInt | None = None
    metric_denominator: PositiveInt | None = None
    normalized_score: int | None = Field(default=None, ge=0, le=100)
    sample_size: PositiveInt = 1
    unit: str | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_metric_payload(self) -> "VendorPerformanceEventCreateValidation":
        if (
            self.metric_value is None
            and self.normalized_score is None
            and (self.metric_numerator is None or self.metric_denominator is None)
        ):
            raise ValueError(
                "Provide MetricValue, NormalizedScore, or both MetricNumerator"
                " and MetricDenominator."
            )

        if (self.metric_numerator is None) != (self.metric_denominator is None):
            raise ValueError(
                "MetricNumerator and MetricDenominator must both be set together."
            )

        return self

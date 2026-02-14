"""Validation schemas used by ops_reporting ACP actions and create payloads."""

from datetime import datetime
from typing import Any, Literal
import uuid

from pydantic import NonNegativeInt, PositiveInt, model_validator

from mugen.core.plugin.acp.contract.api.validation import IValidationBase


class MetricDefinitionCreateValidation(IValidationBase):
    """Validate generic create inputs for MetricDefinition."""

    tenant_id: uuid.UUID | None = None

    code: str
    name: str

    formula_type: Literal[
        "count_rows",
        "sum_column",
        "avg_column",
        "min_column",
        "max_column",
    ] = "count_rows"

    source_table: str
    source_time_column: str | None = None
    source_value_column: str | None = None
    scope_column: str | None = None

    source_filter: dict[str, Any] | None = None
    description: str | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_strings(self) -> "MetricDefinitionCreateValidation":
        if not (self.code or "").strip():
            raise ValueError("Code must be non-empty.")

        if not (self.name or "").strip():
            raise ValueError("Name must be non-empty.")

        if not (self.source_table or "").strip():
            raise ValueError("SourceTable must be non-empty.")

        if self.description is not None and not (self.description or "").strip():
            raise ValueError("Description cannot be empty if provided.")

        if self.formula_type != "count_rows":
            if not (self.source_value_column or "").strip():
                raise ValueError(
                    "SourceValueColumn is required for non-count formula types."
                )

        return self


class AggregationJobCreateValidation(IValidationBase):
    """Validate generic create inputs for AggregationJob."""

    tenant_id: uuid.UUID | None = None
    metric_definition_id: uuid.UUID

    window_start: datetime
    window_end: datetime

    bucket_minutes: PositiveInt = 60
    scope_key: str | None = None
    idempotency_key: str | None = None

    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_window(self) -> "AggregationJobCreateValidation":
        if self.window_end <= self.window_start:
            raise ValueError("WindowEnd must be > WindowStart.")

        if self.scope_key is not None and not (self.scope_key or "").strip():
            raise ValueError("ScopeKey cannot be empty if provided.")

        if self.idempotency_key is not None and not self.idempotency_key.strip():
            raise ValueError("IdempotencyKey cannot be empty if provided.")

        return self


class MetricRunAggregationValidation(IValidationBase):
    """Validate payload for run_aggregation actions."""

    row_version: NonNegativeInt

    window_start: datetime | None = None
    window_end: datetime | None = None

    bucket_minutes: PositiveInt = 60
    scope_key: str | None = None

    note: str | None = None

    @model_validator(mode="after")
    def _validate_window(self) -> "MetricRunAggregationValidation":
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("Provide both WindowStart and WindowEnd together.")

        if (
            self.window_start is not None
            and self.window_end is not None
            and self.window_end <= self.window_start
        ):
            raise ValueError("WindowEnd must be > WindowStart.")

        if self.scope_key is not None and not (self.scope_key or "").strip():
            raise ValueError("ScopeKey cannot be empty if provided.")

        return self


class MetricRecomputeWindowValidation(IValidationBase):
    """Validate payload for recompute_window actions."""

    row_version: NonNegativeInt

    window_start: datetime
    window_end: datetime

    bucket_minutes: PositiveInt = 60
    scope_key: str | None = None

    note: str | None = None

    @model_validator(mode="after")
    def _validate_window(self) -> "MetricRecomputeWindowValidation":
        if self.window_end <= self.window_start:
            raise ValueError("WindowEnd must be > WindowStart.")

        if self.scope_key is not None and not (self.scope_key or "").strip():
            raise ValueError("ScopeKey cannot be empty if provided.")

        return self


class ReportDefinitionCreateValidation(IValidationBase):
    """Validate generic create inputs for ReportDefinition."""

    tenant_id: uuid.UUID | None = None

    code: str
    name: str
    description: str | None = None

    metric_codes: list[str] | None = None

    filters_json: dict[str, Any] | None = None
    group_by_json: list[str] | None = None

    is_active: bool | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_strings(self) -> "ReportDefinitionCreateValidation":
        if not (self.code or "").strip():
            raise ValueError("Code must be non-empty.")

        if not (self.name or "").strip():
            raise ValueError("Name must be non-empty.")

        if self.description is not None and not (self.description or "").strip():
            raise ValueError("Description cannot be empty if provided.")

        if self.metric_codes is not None:
            cleaned = [str(code or "").strip() for code in self.metric_codes]
            if not cleaned or not all(cleaned):
                raise ValueError("MetricCodes must contain non-empty values.")

        return self


class ReportSnapshotCreateValidation(IValidationBase):
    """Validate generic create inputs for ReportSnapshot."""

    tenant_id: uuid.UUID | None = None

    report_definition_id: uuid.UUID | None = None
    metric_codes: list[str] | None = None

    window_start: datetime | None = None
    window_end: datetime | None = None

    scope_key: str | None = None
    note: str | None = None

    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "ReportSnapshotCreateValidation":
        has_report_definition = self.report_definition_id is not None
        has_metric_codes = bool(self.metric_codes)

        if not (has_report_definition or has_metric_codes):
            raise ValueError(
                "Provide ReportDefinitionId or MetricCodes when creating snapshots."
            )

        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("Provide both WindowStart and WindowEnd together.")

        if (
            self.window_start is not None
            and self.window_end is not None
            and self.window_end <= self.window_start
        ):
            raise ValueError("WindowEnd must be > WindowStart.")

        if self.scope_key is not None and not (self.scope_key or "").strip():
            raise ValueError("ScopeKey cannot be empty if provided.")

        return self


class ReportSnapshotGenerateValidation(IValidationBase):
    """Validate payload for generate_snapshot actions."""

    row_version: NonNegativeInt

    window_start: datetime | None = None
    window_end: datetime | None = None

    scope_key: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _validate_window(self) -> "ReportSnapshotGenerateValidation":
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("Provide both WindowStart and WindowEnd together.")

        if (
            self.window_start is not None
            and self.window_end is not None
            and self.window_end <= self.window_start
        ):
            raise ValueError("WindowEnd must be > WindowStart.")

        if self.scope_key is not None and not (self.scope_key or "").strip():
            raise ValueError("ScopeKey cannot be empty if provided.")

        return self


class ReportSnapshotPublishValidation(IValidationBase):
    """Validate payload for publish_snapshot actions."""

    row_version: NonNegativeInt
    note: str | None = None


class ReportSnapshotArchiveValidation(IValidationBase):
    """Validate payload for archive_snapshot actions."""

    row_version: NonNegativeInt
    note: str | None = None


class KpiThresholdCreateValidation(IValidationBase):
    """Validate generic create inputs for KpiThreshold."""

    tenant_id: uuid.UUID | None = None
    metric_definition_id: uuid.UUID

    scope_key: str | None = None

    target_value: int | None = None

    warn_low: int | None = None
    warn_high: int | None = None

    critical_low: int | None = None
    critical_high: int | None = None

    description: str | None = None
    is_active: bool | None = None

    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_ranges(self) -> "KpiThresholdCreateValidation":
        if self.scope_key is not None and not (self.scope_key or "").strip():
            raise ValueError("ScopeKey cannot be empty if provided.")

        if self.warn_low is not None and self.warn_high is not None:
            if self.warn_low > self.warn_high:
                raise ValueError("WarnLow must be <= WarnHigh.")

        if self.critical_low is not None and self.critical_high is not None:
            if self.critical_low > self.critical_high:
                raise ValueError("CriticalLow must be <= CriticalHigh.")

        if self.description is not None and not (self.description or "").strip():
            raise ValueError("Description cannot be empty if provided.")

        return self

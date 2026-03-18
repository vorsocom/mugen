"""Validation schemas used by ops_reporting ACP actions and create payloads."""

from datetime import datetime
from typing import Any, Literal
import uuid

from pydantic import NonNegativeInt, PositiveInt, model_validator

from mugen.core.plugin.acp.api.validation.crud_builder import (
    build_update_validation_from_pascal,
)
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


MetricDefinitionUpdateValidation = build_update_validation_from_pascal(
    "MetricDefinitionUpdateValidation",
    module=__name__,
    doc="Validate update payloads for MetricDefinition.",
    optional_fields=(
        "Code",
        "Name",
        "FormulaType",
        "SourceTable",
        "SourceTimeColumn",
        "SourceValueColumn",
        "ScopeColumn",
        "SourceFilter",
        "Description",
        "IsActive",
        "Attributes",
    ),
)


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


AggregationJobUpdateValidation = build_update_validation_from_pascal(
    "AggregationJobUpdateValidation",
    module=__name__,
    doc="Validate update payloads for AggregationJob.",
    optional_fields=(
        "Status",
        "StartedAt",
        "FinishedAt",
        "LastRunAt",
        "ErrorMessage",
        "Attributes",
    ),
)


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


ReportDefinitionUpdateValidation = build_update_validation_from_pascal(
    "ReportDefinitionUpdateValidation",
    module=__name__,
    doc="Validate update payloads for ReportDefinition.",
    optional_fields=(
        "Code",
        "Name",
        "Description",
        "MetricCodes",
        "FiltersJson",
        "GroupByJson",
        "IsActive",
        "Attributes",
    ),
)


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


ReportSnapshotUpdateValidation = build_update_validation_from_pascal(
    "ReportSnapshotUpdateValidation",
    module=__name__,
    doc="Validate update payloads for ReportSnapshot.",
    optional_fields=(
        "ReportDefinitionId",
        "MetricCodes",
        "WindowStart",
        "WindowEnd",
        "ScopeKey",
        "Note",
        "Attributes",
    ),
)


class ReportSnapshotGenerateValidation(IValidationBase):
    """Validate payload for generate_snapshot actions."""

    row_version: NonNegativeInt

    window_start: datetime | None = None
    window_end: datetime | None = None

    scope_key: str | None = None
    trace_id: str | None = None
    sign: bool = False
    signature_key_id: str | None = None
    provenance_refs_json: dict[str, Any] | list[Any] | None = None
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

        if self.trace_id is not None and not (self.trace_id or "").strip():
            raise ValueError("TraceId cannot be empty if provided.")

        if (
            self.signature_key_id is not None
            and not (self.signature_key_id or "").strip()
        ):
            raise ValueError("SignatureKeyId cannot be empty if provided.")

        return self


class ReportSnapshotPublishValidation(IValidationBase):
    """Validate payload for publish_snapshot actions."""

    row_version: NonNegativeInt
    note: str | None = None


class ReportSnapshotArchiveValidation(IValidationBase):
    """Validate payload for archive_snapshot actions."""

    row_version: NonNegativeInt
    note: str | None = None


class ReportSnapshotVerifyValidation(IValidationBase):
    """Validate payload for verify_snapshot actions."""

    require_clean: bool = False


class ExportJobCreateValidation(IValidationBase):
    """Validate payload for create_export actions."""

    trace_id: str | None = None
    export_type: Literal["report_snapshot_pack", "compliance_pack"]
    spec_json: dict[str, Any]
    sign: bool = True
    signature_key_id: str | None = None
    policy_definition_id: uuid.UUID | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "ExportJobCreateValidation":
        if self.trace_id is not None and not (self.trace_id or "").strip():
            raise ValueError("TraceId cannot be empty if provided.")

        if (
            self.signature_key_id is not None
            and not (self.signature_key_id or "").strip()
        ):
            raise ValueError("SignatureKeyId cannot be empty if provided.")

        resource_refs = self.spec_json.get("ResourceRefs")
        if not isinstance(resource_refs, dict) or len(resource_refs) == 0:
            raise ValueError("SpecJson.ResourceRefs must be a non-empty object.")

        for entity_set, entity_ids in resource_refs.items():
            if not str(entity_set or "").strip():
                raise ValueError("SpecJson.ResourceRefs keys must be non-empty.")
            if not isinstance(entity_ids, list):
                raise ValueError(
                    "SpecJson.ResourceRefs values must be arrays of UUIDs."
                )
            for entity_id in entity_ids:
                try:
                    uuid.UUID(str(entity_id))
                except (TypeError, ValueError) as error:
                    raise ValueError(
                        "SpecJson.ResourceRefs values must be UUIDs."
                    ) from error

        proofs = self.spec_json.get("Proofs")
        if proofs is not None and not isinstance(proofs, dict):
            raise ValueError("SpecJson.Proofs must be an object if provided.")

        export_ref = self.spec_json.get("ExportRef")
        if export_ref is not None and not str(export_ref or "").strip():
            raise ValueError("SpecJson.ExportRef cannot be empty if provided.")

        return self


class ExportJobBuildValidation(IValidationBase):
    """Validate payload for build_export actions."""

    row_version: NonNegativeInt
    force: bool = False
    sign: bool | None = None
    signature_key_id: str | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "ExportJobBuildValidation":
        if (
            self.signature_key_id is not None
            and not (self.signature_key_id or "").strip()
        ):
            raise ValueError("SignatureKeyId cannot be empty if provided.")
        return self


class ExportJobVerifyValidation(IValidationBase):
    """Validate payload for verify_export actions."""

    require_clean: bool = False


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


KpiThresholdUpdateValidation = build_update_validation_from_pascal(
    "KpiThresholdUpdateValidation",
    module=__name__,
    doc="Validate update payloads for KpiThreshold.",
    optional_fields=(
        "ScopeKey",
        "TargetValue",
        "WarnLow",
        "WarnHigh",
        "CriticalLow",
        "CriticalHigh",
        "Description",
        "IsActive",
        "Attributes",
    ),
)

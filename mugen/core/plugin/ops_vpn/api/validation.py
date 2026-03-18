"""Validation schemas used by ops_vpn ACP actions."""

from datetime import datetime
from typing import Any
import uuid

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator

from mugen.core.plugin.acp.api.validation.crud_builder import (
    build_create_validation_from_pascal,
    build_update_validation_from_pascal,
)
from mugen.core.plugin.acp.contract.api.validation import IValidationBase

TaxonomyDomainCreateValidation = build_create_validation_from_pascal(
    "TaxonomyDomainCreateValidation",
    module=__name__,
    doc="Validate create payloads for TaxonomyDomain.",
    required_fields=("TenantId", "Code", "Name"),
)

TaxonomyDomainUpdateValidation = build_update_validation_from_pascal(
    "TaxonomyDomainUpdateValidation",
    module=__name__,
    doc="Validate update payloads for TaxonomyDomain.",
    optional_fields=("Code", "Name", "Description", "Attributes"),
)

TaxonomyCategoryCreateValidation = build_create_validation_from_pascal(
    "TaxonomyCategoryCreateValidation",
    module=__name__,
    doc="Validate create payloads for TaxonomyCategory.",
    required_fields=("TenantId", "TaxonomyDomainId", "Code", "Name"),
)

TaxonomyCategoryUpdateValidation = build_update_validation_from_pascal(
    "TaxonomyCategoryUpdateValidation",
    module=__name__,
    doc="Validate update payloads for TaxonomyCategory.",
    optional_fields=("Code", "Name", "Description", "Attributes"),
)

TaxonomySubcategoryCreateValidation = build_create_validation_from_pascal(
    "TaxonomySubcategoryCreateValidation",
    module=__name__,
    doc="Validate create payloads for TaxonomySubcategory.",
    required_fields=("TenantId", "TaxonomyCategoryId", "Code", "Name"),
)

TaxonomySubcategoryUpdateValidation = build_update_validation_from_pascal(
    "TaxonomySubcategoryUpdateValidation",
    module=__name__,
    doc="Validate update payloads for TaxonomySubcategory.",
    optional_fields=("Code", "Name", "Description", "Attributes"),
)

VendorCreateValidation = build_create_validation_from_pascal(
    "VendorCreateValidation",
    module=__name__,
    doc="Validate create payloads for Vendor.",
    required_fields=("TenantId", "Code", "DisplayName"),
)

VendorUpdateValidation = build_update_validation_from_pascal(
    "VendorUpdateValidation",
    module=__name__,
    doc="Validate update payloads for Vendor.",
    optional_fields=(
        "Code",
        "DisplayName",
        "ReverificationCadenceDays",
        "ExternalRef",
        "Attributes",
    ),
)

VendorCategoryCreateValidation = build_create_validation_from_pascal(
    "VendorCategoryCreateValidation",
    module=__name__,
    doc="Validate create payloads for VendorCategory.",
    required_fields=("TenantId", "VendorId", "CategoryCode"),
)

VendorCategoryUpdateValidation = build_update_validation_from_pascal(
    "VendorCategoryUpdateValidation",
    module=__name__,
    doc="Validate update payloads for VendorCategory.",
    optional_fields=("DisplayName", "Attributes"),
)

VendorCapabilityCreateValidation = build_create_validation_from_pascal(
    "VendorCapabilityCreateValidation",
    module=__name__,
    doc="Validate create payloads for VendorCapability.",
    required_fields=("TenantId", "VendorId", "CapabilityCode", "ServiceRegion"),
)

VendorCapabilityUpdateValidation = build_update_validation_from_pascal(
    "VendorCapabilityUpdateValidation",
    module=__name__,
    doc="Validate update payloads for VendorCapability.",
    optional_fields=("Attributes",),
)

VendorVerificationCreateValidation = build_create_validation_from_pascal(
    "VendorVerificationCreateValidation",
    module=__name__,
    doc="Validate create payloads for VendorVerification.",
    required_fields=("TenantId", "VendorId", "VerificationType", "Status"),
)

VendorVerificationUpdateValidation = build_update_validation_from_pascal(
    "VendorVerificationUpdateValidation",
    module=__name__,
    doc="Validate update payloads for VendorVerification.",
    optional_fields=("CheckedAt", "DueAt", "CheckedByUserId", "Notes", "Attributes"),
)

VerificationCriterionCreateValidation = build_create_validation_from_pascal(
    "VerificationCriterionCreateValidation",
    module=__name__,
    doc="Validate create payloads for VerificationCriterion.",
    required_fields=("TenantId", "Code", "Name"),
)

VerificationCriterionUpdateValidation = build_update_validation_from_pascal(
    "VerificationCriterionUpdateValidation",
    module=__name__,
    doc="Validate update payloads for VerificationCriterion.",
    optional_fields=(
        "Name",
        "Description",
        "VerificationType",
        "IsRequired",
        "SortOrder",
        "Attributes",
    ),
)

VendorVerificationCheckCreateValidation = build_create_validation_from_pascal(
    "VendorVerificationCheckCreateValidation",
    module=__name__,
    doc="Validate create payloads for VendorVerificationCheck.",
    required_fields=("TenantId", "VendorVerificationId", "CriterionCode"),
)

VendorVerificationCheckUpdateValidation = build_update_validation_from_pascal(
    "VendorVerificationCheckUpdateValidation",
    module=__name__,
    doc="Validate update payloads for VendorVerificationCheck.",
    optional_fields=(
        "CriterionId",
        "Status",
        "IsRequired",
        "CheckedAt",
        "DueAt",
        "CheckedByUserId",
        "Notes",
        "Attributes",
    ),
)

VendorVerificationArtifactCreateValidation = build_create_validation_from_pascal(
    "VendorVerificationArtifactCreateValidation",
    module=__name__,
    doc="Validate create payloads for VendorVerificationArtifact.",
    required_fields=("TenantId", "VendorVerificationId", "ArtifactType"),
)

VendorVerificationArtifactUpdateValidation = build_update_validation_from_pascal(
    "VendorVerificationArtifactUpdateValidation",
    module=__name__,
    doc="Validate update payloads for VendorVerificationArtifact.",
    optional_fields=(
        "VerificationCheckId",
        "Uri",
        "ContentHash",
        "UploadedByUserId",
        "UploadedAt",
        "Notes",
        "Attributes",
    ),
)

ScorecardPolicyCreateValidation = build_create_validation_from_pascal(
    "ScorecardPolicyCreateValidation",
    module=__name__,
    doc="Validate create payloads for ScorecardPolicy.",
    required_fields=("TenantId", "Code"),
)

ScorecardPolicyUpdateValidation = build_update_validation_from_pascal(
    "ScorecardPolicyUpdateValidation",
    module=__name__,
    doc="Validate update payloads for ScorecardPolicy.",
    optional_fields=(
        "DisplayName",
        "TimeToQuoteWeight",
        "CompletionRateWeight",
        "ComplaintRateWeight",
        "ResponseSlaWeight",
        "MinSampleSize",
        "MinimumOverallScore",
        "RequireAllMetrics",
        "Attributes",
    ),
)


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

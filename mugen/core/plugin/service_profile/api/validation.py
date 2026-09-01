"""Validation schemas for Service Profile ACP resources and actions."""

__all__ = [
    "ServiceProfileCreateValidation",
    "ServiceProfileIngressBindingCreateValidation",
    "ServiceProfileIngressBindingUpdateValidation",
    "ServiceProfileSubscriptionCreateValidation",
    "ServiceProfileSubscriptionUpdateValidation",
    "ServiceProfileUpdateValidation",
]

from pydantic import model_validator

from mugen.core.plugin.acp.api.validation.crud_builder import (
    build_create_validation_from_pascal,
    build_update_validation_from_pascal,
)

ServiceProfileCreateValidation = build_create_validation_from_pascal(
    "ServiceProfileCreateValidation",
    module=__name__,
    doc="Validate create payloads for ServiceProfile.",
    required_fields=("TenantId", "Key", "DisplayName"),
    optional_fields=("Attributes",),
)

ServiceProfileUpdateValidation = build_update_validation_from_pascal(
    "ServiceProfileUpdateValidation",
    module=__name__,
    doc="Validate update payloads for ServiceProfile.",
    optional_fields=("DisplayName", "Attributes"),
)

ServiceProfileIngressBindingCreateValidation = build_create_validation_from_pascal(
    "ServiceProfileIngressBindingCreateValidation",
    module=__name__,
    doc="Validate create payloads for ServiceProfileIngressBinding.",
    required_fields=("TenantId", "ServiceProfileId", "IngressBindingId"),
    optional_fields=("IsActive", "Attributes"),
)

ServiceProfileIngressBindingUpdateValidation = build_update_validation_from_pascal(
    "ServiceProfileIngressBindingUpdateValidation",
    module=__name__,
    doc="Validate update payloads for ServiceProfileIngressBinding.",
    optional_fields=("IsActive", "Attributes"),
)

_ServiceProfileSubscriptionCreateValidation = build_create_validation_from_pascal(
    "ServiceProfileSubscriptionCreateValidation",
    module=__name__,
    doc="Validate create payloads for ServiceProfileSubscription.",
    required_fields=("TenantId", "ServiceProfileId", "BillingSubscriptionId"),
    optional_fields=("Attributes",),
)


class ServiceProfileSubscriptionCreateValidation(
    _ServiceProfileSubscriptionCreateValidation
):
    """Reject client attempts to set the server-derived Product code."""

    @model_validator(mode="before")
    @classmethod
    def _reject_product_code(cls, values):
        if isinstance(values, dict) and any(
            key in values for key in ("ProductCode", "product_code")
        ):
            raise ValueError("ProductCode is server-derived and must not be provided.")
        return values


ServiceProfileSubscriptionUpdateValidation = build_update_validation_from_pascal(
    "ServiceProfileSubscriptionUpdateValidation",
    module=__name__,
    doc="Validate update payloads for ServiceProfileSubscription.",
    optional_fields=("Attributes",),
)

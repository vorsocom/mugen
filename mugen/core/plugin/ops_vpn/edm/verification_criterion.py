"""Provides the verification criterion EDM type definition."""

__all__ = ["verification_criterion_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

verification_criterion_type = EdmType(
    name="OPSVPN.VerificationCriterion",
    kind="entity",
    properties={
        "Id": EdmProperty("Id", TypeRef("Edm.Guid"), nullable=False),
        "CreatedAt": EdmProperty(
            "CreatedAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "UpdatedAt": EdmProperty(
            "UpdatedAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "RowVersion": EdmProperty("RowVersion", TypeRef("Edm.Int64"), nullable=False),
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid"), nullable=False),
        "Code": EdmProperty("Code", TypeRef("Edm.String"), nullable=False),
        "Name": EdmProperty("Name", TypeRef("Edm.String"), nullable=False),
        "Description": EdmProperty("Description", TypeRef("Edm.String")),
        "VerificationType": EdmProperty("VerificationType", TypeRef("Edm.String")),
        "IsRequired": EdmProperty("IsRequired", TypeRef("Edm.Boolean"), nullable=False),
        "SortOrder": EdmProperty("SortOrder", TypeRef("Edm.Int64"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    nav_properties={
        "VerificationChecks": EdmNavigationProperty(
            "VerificationChecks",
            target_type=TypeRef("OPSVPN.VendorVerificationCheck", is_collection=True),
            target_fk="CriterionId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsVpnVerificationCriteria",
)

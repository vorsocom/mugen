"""Provides the vendor verification check EDM type definition."""

__all__ = ["vendor_verification_check_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

vendor_verification_check_type = EdmType(
    name="OPSVPN.VendorVerificationCheck",
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
        "VendorVerificationId": EdmProperty(
            "VendorVerificationId", TypeRef("Edm.Guid"), nullable=False
        ),
        "CriterionId": EdmProperty("CriterionId", TypeRef("Edm.Guid")),
        "CriterionCode": EdmProperty(
            "CriterionCode", TypeRef("Edm.String"), nullable=False
        ),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "IsRequired": EdmProperty("IsRequired", TypeRef("Edm.Boolean"), nullable=False),
        "CheckedAt": EdmProperty("CheckedAt", TypeRef("Edm.DateTimeOffset")),
        "DueAt": EdmProperty("DueAt", TypeRef("Edm.DateTimeOffset")),
        "CheckedByUserId": EdmProperty("CheckedByUserId", TypeRef("Edm.Guid")),
        "Notes": EdmProperty("Notes", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    nav_properties={
        "VendorVerification": EdmNavigationProperty(
            "VendorVerification",
            target_type=TypeRef("OPSVPN.VendorVerification"),
            source_fk="VendorVerificationId",
        ),
        "Criterion": EdmNavigationProperty(
            "Criterion",
            target_type=TypeRef("OPSVPN.VerificationCriterion"),
            source_fk="CriterionId",
        ),
        "Artifacts": EdmNavigationProperty(
            "Artifacts",
            target_type=TypeRef(
                "OPSVPN.VendorVerificationArtifact",
                is_collection=True,
            ),
            target_fk="VerificationCheckId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsVpnVendorVerificationChecks",
)

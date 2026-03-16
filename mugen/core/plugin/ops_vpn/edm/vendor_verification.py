"""Provides the vendor verification EDM type definition."""

__all__ = ["vendor_verification_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

vendor_verification_type = EdmType(
    name="OPSVPN.VendorVerification",
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
        "VendorId": EdmProperty("VendorId", TypeRef("Edm.Guid"), nullable=False),
        "VerificationType": EdmProperty(
            "VerificationType", TypeRef("Edm.String"), nullable=False
        ),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "CheckedAt": EdmProperty(
            "CheckedAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
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
        "Vendor": EdmNavigationProperty(
            "Vendor",
            target_type=TypeRef("OPSVPN.Vendor"),
            source_fk="VendorId",
        ),
        "VerificationChecks": EdmNavigationProperty(
            "VerificationChecks",
            target_type=TypeRef("OPSVPN.VendorVerificationCheck", is_collection=True),
            target_fk="VendorVerificationId",
        ),
        "VerificationArtifacts": EdmNavigationProperty(
            "VerificationArtifacts",
            target_type=TypeRef(
                "OPSVPN.VendorVerificationArtifact",
                is_collection=True,
            ),
            target_fk="VendorVerificationId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsVpnVendorVerifications",
)

"""Provides the vendor verification artifact EDM type definition."""

__all__ = ["vendor_verification_artifact_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

vendor_verification_artifact_type = EdmType(
    name="OPSVPN.VendorVerificationArtifact",
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
        "VerificationCheckId": EdmProperty(
            "VerificationCheckId", TypeRef("Edm.Guid")
        ),
        "ArtifactType": EdmProperty(
            "ArtifactType",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "Uri": EdmProperty("Uri", TypeRef("Edm.String")),
        "ContentHash": EdmProperty("ContentHash", TypeRef("Edm.String")),
        "UploadedByUserId": EdmProperty("UploadedByUserId", TypeRef("Edm.Guid")),
        "UploadedAt": EdmProperty(
            "UploadedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
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
        "VerificationCheck": EdmNavigationProperty(
            "VerificationCheck",
            target_type=TypeRef("OPSVPN.VendorVerificationCheck"),
            source_fk="VerificationCheckId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsVpnVendorVerificationArtifacts",
)

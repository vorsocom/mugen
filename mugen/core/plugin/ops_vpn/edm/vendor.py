"""Provides the vendor EDM type definition."""

__all__ = ["vendor_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

vendor_type = EdmType(
    name="OPSVPN.Vendor",
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
        "DisplayName": EdmProperty(
            "DisplayName", TypeRef("Edm.String"), nullable=False
        ),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "OnboardingCompletedAt": EdmProperty(
            "OnboardingCompletedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "ReverificationCadenceDays": EdmProperty(
            "ReverificationCadenceDays",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "LastReverifiedAt": EdmProperty(
            "LastReverifiedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "NextReverificationDueAt": EdmProperty(
            "NextReverificationDueAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "ExternalRef": EdmProperty("ExternalRef", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "DeletedAt": EdmProperty("DeletedAt", TypeRef("Edm.DateTimeOffset")),
        "DeletedByUserId": EdmProperty("DeletedByUserId", TypeRef("Edm.Guid")),
    },
    nav_properties={
        "VendorCategories": EdmNavigationProperty(
            "VendorCategories",
            target_type=TypeRef("OPSVPN.VendorCategory", is_collection=True),
            target_fk="VendorId",
        ),
        "VendorCapabilities": EdmNavigationProperty(
            "VendorCapabilities",
            target_type=TypeRef("OPSVPN.VendorCapability", is_collection=True),
            target_fk="VendorId",
        ),
        "VendorVerifications": EdmNavigationProperty(
            "VendorVerifications",
            target_type=TypeRef("OPSVPN.VendorVerification", is_collection=True),
            target_fk="VendorId",
        ),
        "VendorPerformanceEvents": EdmNavigationProperty(
            "VendorPerformanceEvents",
            target_type=TypeRef("OPSVPN.VendorPerformanceEvent", is_collection=True),
            target_fk="VendorId",
        ),
        "VendorScorecards": EdmNavigationProperty(
            "VendorScorecards",
            target_type=TypeRef("OPSVPN.VendorScorecard", is_collection=True),
            target_fk="VendorId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsVpnVendors",
)

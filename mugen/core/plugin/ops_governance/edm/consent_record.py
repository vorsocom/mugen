"""Provides the consent record EDM type definition."""

__all__ = ["consent_record_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

consent_record_type = EdmType(
    name="OPSGOVERNANCE.ConsentRecord",
    kind="entity",
    properties={
        "Id": EdmProperty("Id", TypeRef("Edm.Guid"), nullable=False),
        "CreatedAt": EdmProperty(
            "CreatedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "UpdatedAt": EdmProperty(
            "UpdatedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "RowVersion": EdmProperty("RowVersion", TypeRef("Edm.Int64"), nullable=False),
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid"), nullable=False),
        "SubjectUserId": EdmProperty(
            "SubjectUserId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "ControllerNamespace": EdmProperty(
            "ControllerNamespace",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "Purpose": EdmProperty("Purpose", TypeRef("Edm.String"), nullable=False),
        "Scope": EdmProperty("Scope", TypeRef("Edm.String"), nullable=False),
        "LegalBasis": EdmProperty("LegalBasis", TypeRef("Edm.String")),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "EffectiveAt": EdmProperty(
            "EffectiveAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "ExpiresAt": EdmProperty("ExpiresAt", TypeRef("Edm.DateTimeOffset")),
        "SourceConsentId": EdmProperty("SourceConsentId", TypeRef("Edm.Guid")),
        "WithdrawnAt": EdmProperty("WithdrawnAt", TypeRef("Edm.DateTimeOffset")),
        "WithdrawnByUserId": EdmProperty("WithdrawnByUserId", TypeRef("Edm.Guid")),
        "WithdrawalReason": EdmProperty("WithdrawalReason", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsConsentRecords",
)

"""Provides the retention policy EDM type definition."""

__all__ = ["retention_policy_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

retention_policy_type = EdmType(
    name="OPSGOVERNANCE.RetentionPolicy",
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
        "Code": EdmProperty("Code", TypeRef("Edm.String"), nullable=False),
        "Name": EdmProperty("Name", TypeRef("Edm.String"), nullable=False),
        "TargetNamespace": EdmProperty(
            "TargetNamespace",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "TargetEntity": EdmProperty("TargetEntity", TypeRef("Edm.String")),
        "Description": EdmProperty("Description", TypeRef("Edm.String")),
        "RetentionDays": EdmProperty(
            "RetentionDays",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "RedactionAfterDays": EdmProperty(
            "RedactionAfterDays",
            TypeRef("Edm.Int64"),
        ),
        "LegalHoldAllowed": EdmProperty(
            "LegalHoldAllowed",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "ActionMode": EdmProperty("ActionMode", TypeRef("Edm.String"), nullable=False),
        "DownstreamJobRef": EdmProperty("DownstreamJobRef", TypeRef("Edm.String")),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "LastActionAppliedAt": EdmProperty(
            "LastActionAppliedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "LastActionType": EdmProperty("LastActionType", TypeRef("Edm.String")),
        "LastActionStatus": EdmProperty("LastActionStatus", TypeRef("Edm.String")),
        "LastActionNote": EdmProperty("LastActionNote", TypeRef("Edm.String")),
        "LastActionByUserId": EdmProperty("LastActionByUserId", TypeRef("Edm.Guid")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsRetentionPolicies",
)

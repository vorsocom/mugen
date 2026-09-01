"""Provides the Knowledge Index Projection EDM type definition."""

__all__ = ["knowledge_index_projection_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

knowledge_index_projection_type = EdmType(
    name="KNOWLEDGEPACK.KnowledgeIndexProjection",
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
        "KnowledgePackId": EdmProperty(
            "KnowledgePackId", TypeRef("Edm.Guid"), nullable=False
        ),
        "KnowledgePackVersionId": EdmProperty(
            "KnowledgePackVersionId", TypeRef("Edm.Guid"), nullable=False
        ),
        "Provider": EdmProperty("Provider", TypeRef("Edm.String"), nullable=False),
        "TargetFingerprint": EdmProperty(
            "TargetFingerprint", TypeRef("Edm.String"), nullable=False
        ),
        "ContentChecksum": EdmProperty(
            "ContentChecksum", TypeRef("Edm.String"), nullable=False
        ),
        "ProjectionSchemaVersion": EdmProperty(
            "ProjectionSchemaVersion", TypeRef("Edm.Int64"), nullable=False
        ),
        "Operation": EdmProperty("Operation", TypeRef("Edm.String"), nullable=False),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "DocumentCount": EdmProperty(
            "DocumentCount", TypeRef("Edm.Int64"), nullable=False
        ),
        "AttemptCount": EdmProperty(
            "AttemptCount", TypeRef("Edm.Int64"), nullable=False
        ),
        "MaxAttempts": EdmProperty("MaxAttempts", TypeRef("Edm.Int64"), nullable=False),
        "LeaseOwner": EdmProperty("LeaseOwner", TypeRef("Edm.String")),
        "LeaseExpiresAt": EdmProperty("LeaseExpiresAt", TypeRef("Edm.DateTimeOffset")),
        "RequestedByUserId": EdmProperty("RequestedByUserId", TypeRef("Edm.Guid")),
        "RequestedAt": EdmProperty(
            "RequestedAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "StartedAt": EdmProperty("StartedAt", TypeRef("Edm.DateTimeOffset")),
        "CompletedAt": EdmProperty("CompletedAt", TypeRef("Edm.DateTimeOffset")),
        "FailedAt": EdmProperty("FailedAt", TypeRef("Edm.DateTimeOffset")),
        "FailureCode": EdmProperty("FailureCode", TypeRef("Edm.String")),
        "FailureDetail": EdmProperty("FailureDetail", TypeRef("Edm.String")),
        "IsCurrentReady": EdmProperty(
            "IsCurrentReady", TypeRef("Edm.Boolean"), nullable=False
        ),
        "RequestPayload": EdmProperty(
            "RequestPayload",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    nav_properties={
        "KnowledgePack": EdmNavigationProperty(
            "KnowledgePack",
            target_type=TypeRef("KNOWLEDGEPACK.KnowledgePack"),
            source_fk="KnowledgePackId",
        ),
        "KnowledgePackVersion": EdmNavigationProperty(
            "KnowledgePackVersion",
            target_type=TypeRef("KNOWLEDGEPACK.KnowledgePackVersion"),
            source_fk="KnowledgePackVersionId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="KnowledgeIndexProjections",
)

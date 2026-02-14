"""Provides the knowledge approval EDM type definition."""

__all__ = ["knowledge_approval_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

knowledge_approval_type = EdmType(
    name="KNOWLEDGEPACK.KnowledgeApproval",
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
        "KnowledgePackVersionId": EdmProperty(
            "KnowledgePackVersionId", TypeRef("Edm.Guid"), nullable=False
        ),
        "KnowledgeEntryRevisionId": EdmProperty(
            "KnowledgeEntryRevisionId", TypeRef("Edm.Guid")
        ),
        "Action": EdmProperty("Action", TypeRef("Edm.String"), nullable=False),
        "ActorUserId": EdmProperty("ActorUserId", TypeRef("Edm.Guid")),
        "OccurredAt": EdmProperty(
            "OccurredAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "Note": EdmProperty("Note", TypeRef("Edm.String")),
        "Payload": EdmProperty(
            "Payload",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    nav_properties={
        "KnowledgePackVersion": EdmNavigationProperty(
            "KnowledgePackVersion",
            target_type=TypeRef("KNOWLEDGEPACK.KnowledgePackVersion"),
            source_fk="KnowledgePackVersionId",
        ),
        "KnowledgeEntryRevision": EdmNavigationProperty(
            "KnowledgeEntryRevision",
            target_type=TypeRef("KNOWLEDGEPACK.KnowledgeEntryRevision"),
            source_fk="KnowledgeEntryRevisionId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="KnowledgeApprovals",
)

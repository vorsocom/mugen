"""Provides the knowledge scope EDM type definition."""

__all__ = ["knowledge_scope_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

knowledge_scope_type = EdmType(
    name="KNOWLEDGEPACK.KnowledgeScope",
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
            "KnowledgeEntryRevisionId", TypeRef("Edm.Guid"), nullable=False
        ),
        "Channel": EdmProperty("Channel", TypeRef("Edm.String")),
        "Locale": EdmProperty("Locale", TypeRef("Edm.String")),
        "Category": EdmProperty("Category", TypeRef("Edm.String")),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
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
    entity_set_name="KnowledgeScopes",
)

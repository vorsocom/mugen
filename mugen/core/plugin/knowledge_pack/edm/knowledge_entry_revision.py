"""Provides the knowledge entry revision EDM type definition."""

__all__ = ["knowledge_entry_revision_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

knowledge_entry_revision_type = EdmType(
    name="KNOWLEDGEPACK.KnowledgeEntryRevision",
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
        "KnowledgeEntryId": EdmProperty(
            "KnowledgeEntryId", TypeRef("Edm.Guid"), nullable=False
        ),
        "KnowledgePackVersionId": EdmProperty(
            "KnowledgePackVersionId", TypeRef("Edm.Guid"), nullable=False
        ),
        "RevisionNumber": EdmProperty(
            "RevisionNumber", TypeRef("Edm.Int64"), nullable=False
        ),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "Body": EdmProperty("Body", TypeRef("Edm.String")),
        "BodyJson": EdmProperty(
            "BodyJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "Channel": EdmProperty("Channel", TypeRef("Edm.String")),
        "Locale": EdmProperty("Locale", TypeRef("Edm.String")),
        "Category": EdmProperty("Category", TypeRef("Edm.String")),
        "PublishedAt": EdmProperty("PublishedAt", TypeRef("Edm.DateTimeOffset")),
        "PublishedByUserId": EdmProperty("PublishedByUserId", TypeRef("Edm.Guid")),
        "ArchivedAt": EdmProperty("ArchivedAt", TypeRef("Edm.DateTimeOffset")),
        "ArchivedByUserId": EdmProperty("ArchivedByUserId", TypeRef("Edm.Guid")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    nav_properties={
        "KnowledgeEntry": EdmNavigationProperty(
            "KnowledgeEntry",
            target_type=TypeRef("KNOWLEDGEPACK.KnowledgeEntry"),
            source_fk="KnowledgeEntryId",
        ),
        "KnowledgePackVersion": EdmNavigationProperty(
            "KnowledgePackVersion",
            target_type=TypeRef("KNOWLEDGEPACK.KnowledgePackVersion"),
            source_fk="KnowledgePackVersionId",
        ),
        "Scopes": EdmNavigationProperty(
            "Scopes",
            target_type=TypeRef("KNOWLEDGEPACK.KnowledgeScope", is_collection=True),
            target_fk="KnowledgeEntryRevisionId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="KnowledgeEntryRevisions",
)

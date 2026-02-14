"""Provides the knowledge entry EDM type definition."""

__all__ = ["knowledge_entry_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

knowledge_entry_type = EdmType(
    name="KNOWLEDGEPACK.KnowledgeEntry",
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
        "EntryKey": EdmProperty("EntryKey", TypeRef("Edm.String"), nullable=False),
        "Title": EdmProperty("Title", TypeRef("Edm.String"), nullable=False),
        "Summary": EdmProperty("Summary", TypeRef("Edm.String")),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
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
        "Revisions": EdmNavigationProperty(
            "Revisions",
            target_type=TypeRef(
                "KNOWLEDGEPACK.KnowledgeEntryRevision",
                is_collection=True,
            ),
            target_fk="KnowledgeEntryId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="KnowledgeEntries",
)

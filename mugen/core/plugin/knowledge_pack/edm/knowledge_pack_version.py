"""Provides the knowledge pack version EDM type definition."""

__all__ = ["knowledge_pack_version_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

knowledge_pack_version_type = EdmType(
    name="KNOWLEDGEPACK.KnowledgePackVersion",
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
        "VersionNumber": EdmProperty(
            "VersionNumber", TypeRef("Edm.Int64"), nullable=False
        ),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "SubmittedAt": EdmProperty("SubmittedAt", TypeRef("Edm.DateTimeOffset")),
        "SubmittedByUserId": EdmProperty("SubmittedByUserId", TypeRef("Edm.Guid")),
        "ApprovedAt": EdmProperty("ApprovedAt", TypeRef("Edm.DateTimeOffset")),
        "ApprovedByUserId": EdmProperty("ApprovedByUserId", TypeRef("Edm.Guid")),
        "PublishedAt": EdmProperty("PublishedAt", TypeRef("Edm.DateTimeOffset")),
        "PublishedByUserId": EdmProperty("PublishedByUserId", TypeRef("Edm.Guid")),
        "ArchivedAt": EdmProperty("ArchivedAt", TypeRef("Edm.DateTimeOffset")),
        "ArchivedByUserId": EdmProperty("ArchivedByUserId", TypeRef("Edm.Guid")),
        "RollbackOfVersionId": EdmProperty(
            "RollbackOfVersionId", TypeRef("Edm.Guid")
        ),
        "Note": EdmProperty("Note", TypeRef("Edm.String")),
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
        "Entries": EdmNavigationProperty(
            "Entries",
            target_type=TypeRef("KNOWLEDGEPACK.KnowledgeEntry", is_collection=True),
            target_fk="KnowledgePackVersionId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="KnowledgePackVersions",
)

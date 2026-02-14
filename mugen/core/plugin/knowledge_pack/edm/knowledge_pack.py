"""Provides the knowledge pack EDM type definition."""

__all__ = ["knowledge_pack_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

knowledge_pack_type = EdmType(
    name="KNOWLEDGEPACK.KnowledgePack",
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
        "Key": EdmProperty("Key", TypeRef("Edm.String"), nullable=False),
        "Name": EdmProperty("Name", TypeRef("Edm.String"), nullable=False),
        "Description": EdmProperty("Description", TypeRef("Edm.String")),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "CurrentVersionId": EdmProperty("CurrentVersionId", TypeRef("Edm.Guid")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    nav_properties={
        "CurrentVersion": EdmNavigationProperty(
            "CurrentVersion",
            target_type=TypeRef("KNOWLEDGEPACK.KnowledgePackVersion"),
            source_fk="CurrentVersionId",
        ),
        "Versions": EdmNavigationProperty(
            "Versions",
            target_type=TypeRef(
                "KNOWLEDGEPACK.KnowledgePackVersion",
                is_collection=True,
            ),
            target_fk="KnowledgePackId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="KnowledgePacks",
)

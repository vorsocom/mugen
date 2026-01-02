"""Provides an EdmType for the User declarative model."""

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

person_type = EdmType(
    name="ACP.Person",
    kind="entity",
    properties={
        # ModelBase.
        "Id": EdmProperty(
            "Id",
            TypeRef("Edm.Guid"),
        ),
        "CreatedAt": EdmProperty(
            "CreatedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "UpdatedAt": EdmProperty(
            "UpdatedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "RowVersion": EdmProperty(
            "RowVersion",
            TypeRef("Edm.Int64"),
        ),
        # Person
        "FirstName": EdmProperty(
            "FirstName",
            TypeRef("Edm.String"),
        ),
        "LastName": EdmProperty(
            "LastName",
            TypeRef("Edm.String"),
        ),
    },
    nav_properties={
        "User": EdmNavigationProperty(
            "User",
            target_type=TypeRef(
                "ACP.User",
                is_collection=False,
            ),
            source_fk="UserId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="Persons",
)

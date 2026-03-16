"""Provides an EdmType for the SystemFlag declarative model."""

from mugen.core.utility.rgql.model import (
    EdmProperty,
    EdmType,
    TypeRef,
)

system_flag_type = EdmType(
    name="ACP.SystemFlag",
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
        # SystemFlag.
        "Namespace": EdmProperty(
            "Namespace",
            TypeRef("Edm.String"),
        ),
        "Name": EdmProperty(
            "Name",
            TypeRef("Edm.String"),
        ),
        "Description": EdmProperty(
            "Description",
            TypeRef("Edm.String"),
        ),
        "IsSet": EdmProperty(
            "IsSet",
            TypeRef("Edm.Boolean"),
        ),
    },
    key_properties=("Id",),
    entity_set_name="SystemFlags",
)

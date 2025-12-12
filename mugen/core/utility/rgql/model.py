"""Light-weight in-memory metadata model used by the RGQL semantic layer.

The classes in this module provide just enough structure to express
entity, complex and enumeration types together with entity sets. The
semantic checker uses this information to resolve property paths,
navigation properties and type names that appear in parsed URLs and
expressions.

This is not a full EDM implementation; it is a compact representation
tailored for RGQL.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Tuple


@dataclass(frozen=True)
class TypeRef:
    """
    EDM type reference.

    name          : fully-qualified EDM type, e.g. "NS.Customer", "Edm.String"
    is_collection : True for collections of that type
    """

    name: str
    is_collection: bool = False

    def element(self) -> "TypeRef":
        """Return a single-valued reference to the same EDM type.

        If this instance represents a collection (``is_collection`` is
        ``True``), the returned :class:`TypeRef` has the same ``name``
        but with ``is_collection`` set to ``False``.  Otherwise, the
        current instance is returned unchanged.
        """
        if self.is_collection:
            return TypeRef(self.name, is_collection=False)
        return self


@dataclass
class EdmProperty:
    """Structural property of an EDM type.

    Attributes
    ----------
    name:
        Property name as used in queries.
    type:
        :class:`TypeRef` describing the property's EDM type.
    nullable:
        Whether the property is allowed to have a null value.
    filterable:
        Whether the property may be used in $filter expressions.
    sortable:
        Whether the property may be used in $orderby expressions.
    """

    name: str
    type: TypeRef
    nullable: bool = True
    filterable: bool = True
    sortable: bool = True
    redact: bool = False


@dataclass
class EdmNavigationProperty:
    """Navigation property linking one type to another.

    ``target_type`` is a :class:`TypeRef` describing the entity type at
    the other end of the relationship.  ``nullable`` indicates whether
    the navigation can be missing (for single-valued navigations).
    """

    name: str
    target_type: TypeRef
    nullable: bool = True


@dataclass
class EdmType:
    """
    EDM type definition.

    kind:
      - "primitive"
      - "enum"
      - "complex"
      - "entity"

    For enum types, enum_members holds the allowed symbolic values.
    For other kinds it is usually empty.

    For entity types, key_properties (when set) lists the property
    names that form the primary key in canonical order.
    """

    name: str
    kind: str
    base_type: Optional[str] = None

    properties: Dict[str, EdmProperty] = field(default_factory=dict)
    nav_properties: Dict[str, EdmNavigationProperty] = field(default_factory=dict)

    # Only meaningful when kind == "enum"
    enum_members: Set[str] = field(default_factory=set)

    # Only meaningful when kind == "entity"
    key_properties: Optional[Tuple[str, ...]] = None

    def find_property(self, name: str) -> Optional[EdmProperty]:
        """Look up a structural property by name on this type.

        Only properties declared directly on this type are considered.
        In a fuller implementation this method could walk the base type
        chain as well.
        """
        prop = self.properties.get(name)
        if prop:
            return prop
        # In a full implementation, look into base_type
        return None

    def find_nav_property(self, name: str) -> Optional[EdmNavigationProperty]:
        """Look up a navigation property by name on this type.

        Only properties declared directly on this type are considered.
        """
        nav = self.nav_properties.get(name)
        if nav:
            return nav
        return None

    def property_redacted(self, name: str) -> bool:
        """Check if a field is redacted."""
        prop = self.properties.get(name)
        if prop:
            return prop.redact
        return False


@dataclass
class EntitySet:
    """Top-level collection or singleton of entities.

    Attributes
    ----------
    name:
        Name used in the resource path.
    type:
        :class:`TypeRef` pointing at the entity type.
    is_singleton:
        ``True`` if this represents a singleton instance rather than a
        collection.
    """

    name: str
    type: TypeRef
    is_singleton: bool = False


@dataclass
class EdmModel:
    """In-memory metadata model used by the semantic checker.

    The model stores EDM types (primitive, enum, complex, entity) and
    top-level entity sets / singletons.  It is intentionally minimal but
    sufficient for validating typical RGQL queries.
    """

    types: Dict[str, EdmType] = field(default_factory=dict)
    entity_sets: Dict[str, EntitySet] = field(default_factory=dict)

    def add_type(self, t: EdmType) -> None:
        """Register an :class:`EdmType` in the model.

        If another type with the same name already exists it will be
        silently overwritten.
        """
        self.types[t.name] = t

    def add_entity_set(self, es: EntitySet) -> None:
        """Register an :class:`EntitySet` in the model.

        If another entity set with the same name already exists it will
        be silently overwritten.
        """
        self.entity_sets[es.name] = es

    def get_type(self, name: str) -> EdmType:
        """Return the EDM type with the given name, or raise ``KeyError``.

        This is a convenience wrapper around the underlying dictionary
        and is typically used when the caller expects the type to exist.
        """
        try:
            return self.types[name]
        except KeyError as exc:
            raise KeyError(f"Unknown EDM type {name!r}") from exc

    def try_get_type(self, name: str) -> Optional[EdmType]:
        """Return the EDM type with the given name, or ``None`` if it is
        not registered in the model.
        """
        return self.types.get(name)

    def get_entity_set(self, name: str) -> EntitySet:
        """Look up an entity set by name.

        If the entity set is not present in the model, a
        :class:`KeyError` is raised. This is useful in code paths where a
        missing set should be treated as a hard error.
        """
        try:
            return self.entity_sets[name]
        except KeyError as exc:
            raise KeyError(f"Unknown entity set {name!r}") from exc

    def try_get_entity_set(self, name: str) -> Optional[EntitySet]:
        """Return the entity set or singleton with the given name, or
        ``None`` if it is not registered in the model.
        """
        return self.entity_sets.get(name)

    def set_entity_keys(self, type_name: str, *key_props: str) -> None:
        """Declare the primary key properties for an entity type.

        Parameters
        ----------
        type_name:
            Name of the EDM entity type whose key is being configured.
        key_props:
            One or more property names that together form the primary key.
            The order of the names is the canonical key order.

        Raises
        ------
        KeyError
            If no type with ``type_name`` is registered in the model.
        ValueError
            If the resolved type is not an entity type, or if any of the
            given property names does not exist as a structural property
            on that type.

        Notes
        -----
        This method populates :attr:`EdmType.key_properties` for the target
        entity type. Existing key metadata for the type is overwritten.
        The semantic checker uses this information to validate key
        predicates in resource paths and to enable OData 4.01 key-as-segment
        handling.
        """
        t = self.get_type(type_name)
        if t.kind != "entity":
            raise ValueError(
                f"Keys can only be defined on entity types, got {t.kind!r}"
            )
        for kp in key_props:
            if kp not in t.properties:
                raise ValueError(f"{kp!r} is not a property of {type_name!r}")
        t.key_properties = tuple(key_props)

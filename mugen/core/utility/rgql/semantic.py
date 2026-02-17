# pylint: disable=too-many-lines
"""Semantic checking for RGQL expressions, URLs, and transformation pipelines.

This module walks the AST produced by the parsers and validates it against
an :class:`EdmModel`.  It is responsible for:

  * resolving resource paths against entity sets and navigation properties
  * type checking expressions
  * validating query options such as ``$filter``, ``$orderby``,
    ``$select``, ``$expand`` and ``$apply``
  * enforcing rules on transformation pipelines (groupby/aggregate,
    top/bottom, etc.)

The goal is to catch model- and type-related issues after parsing but
before executing a query.
"""

from dataclasses import dataclass
import datetime
import decimal
from typing import Any, Dict, List, Optional
import uuid

from mugen.core.utility.rgql.apply_parser import (
    ApplyNode,
    AggregateTransform,
    GroupByTransform,
    BottomTopTransform,
    FilterTransform,
    OrderByTransform,
    SearchTransform,
    SkipTransform,
    TopTransform,
    IdentityTransform,
    ComputeTransform,
    ComputeExpression,
    ConcatTransform,
    CustomApplyTransform,
)
from mugen.core.utility.rgql.ast import (
    Expr,
    Literal,
    Identifier,
    MemberAccess,
    BinaryOp,
    UnaryOp,
    FunctionCall,
    LambdaCall,
    CastExpr,
    IsOfExpr,
    EnumLiteral,
    SpatialLiteral,
    is_boolean_expr,
)
from mugen.core.utility.rgql.expr_parser import parse_rgql_expr, ParseError
from mugen.core.utility.rgql.model import EdmModel, EdmType
from mugen.core.utility.rgql.url_parser import (
    RGQLUrl,
    RGQLPathSegment,
    RGQLQueryOptions,
    OrderByItem,
    ExpandItem,
    KeyComponent,
)


class SemanticError(Exception):
    """Error raised when a parsed URL or expression is not semantically valid.

    Examples include:

      * referencing a non-existent entity set, property, or navigation
      * applying an operator to incompatible types
      * using a non-boolean expression where a predicate is required
      * specifying an invalid transformation pipeline

    The parser focuses on syntactic correctness; this exception covers
    the second phase where model- and type-based rules are enforced.
    """


@dataclass(frozen=True)
class ValueType:
    """
    Static type of an expression as seen by the semantic layer.

    type_name     : fully-qualified EDM type (e.g. "Edm.String", "NS.Customer")
    is_collection : True if it represents a collection of that type
    """

    type_name: str
    is_collection: bool = False

    def element(self) -> "ValueType":
        """Return the element type of a collection, or ``self`` if this is
        already a single value.

        This is a lightweight helper used throughout the semantic
        checker when reasoning about collection-valued expressions (for
        example, the source of a lambda expression).
        """
        return ValueType(self.type_name, is_collection=False)


class SemanticChecker:  # pylint: disable=too-few-public-methods
    """Semantic checker for parsed RGQL URLs and expressions.

    Responsibilities:

      * resolve the resource path against an :class:`EdmModel`
      * validate ``$select``, ``$expand``, ``$filter`` and ``$orderby``
      * validate ``$apply`` transformation pipelines
      * interpret:
          - JSON literals as complex/collection values
          - string literals as unprefixed enum literals when appropriate
          - parameter aliases (``@p1``) with types inferred from their
            definitions
    """

    def __init__(self, model: EdmModel):
        self.model = model
        self._expr_context: Optional[str] = None  # "filter", "orderby", or None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_url(self, url: RGQLUrl) -> None:
        """Perform full semantic validation of a parsed URL.

        The method walks the resource path and all query options,
        resolving them against the supplied :class:`EdmModel`.  If any
        inconsistency is found it raises :class:`SemanticError`; on
        success it returns ``None``.

        No state is stored on the :class:`RGQLUrl` instance itself – the
        checker is side-effect free.
        """
        base_type = self._check_resource_path(url.resource_path)
        alias_env = self._build_alias_env(base_type, url.query)
        self._check_query_options(base_type, url.query, alias_env)

    def materialize_expand_for_url(self, url: RGQLUrl) -> List[ExpandItem]:
        """Return a normalized list of :class:`ExpandItem` for ``url``.

        Any wildcard ``*`` expand items (at any nesting level) are
        expanded into concrete navigation paths based on the model.
        The original :class:`RGQLUrl` is not modified.
        """
        base_type = self._check_resource_path(url.resource_path)
        expand = url.query.expand or []
        return self._materialize_expand_items(expand, base_type)

    # ------------------------------------------------------------------
    # Resource path
    # ------------------------------------------------------------------

    def _check_resource_path(self, segments: List[RGQLPathSegment]) -> ValueType:
        if not segments:
            raise SemanticError("Resource path is empty")

        first = segments[0]
        es = self.model.try_get_entity_set(first.name)
        if es is None:
            raise SemanticError(f"Unknown entity set or singleton: {first.name!r}")

        current = ValueType(es.type.name, is_collection=not es.is_singleton)

        if first.key_components is not None:
            current = self._apply_key(current, first)
        elif first.key_predicate is not None:
            # Backwards-compat: if for some reason key_components was
            # not populated, fall back to simple narrowing.
            if not current.is_collection:
                raise SemanticError(
                    f"Key predicate not allowed on singleton: {first.name!r}"
                )
            current = ValueType(current.type_name, is_collection=False)

        for seg in segments[1:]:
            if seg.is_count:
                if not current.is_collection:
                    raise SemanticError("$count is only allowed on collections")
                current = ValueType("Edm.Int64", is_collection=False)
                continue

            current = self._resolve_segment(current, seg)

        return current

    # pylint: disable=too-many-branches
    def _apply_key(self, current: ValueType, seg: RGQLPathSegment) -> ValueType:
        """
        Apply a key predicate to a collection of entities.

        Uses seg.key_components (parsed by the URL parser) together with
        entity key metadata from the model to validate shape and types,
        and returns the narrowed single-valued type.
        """
        if not current.is_collection:
            raise SemanticError(f"Key predicate not allowed on singleton: {seg.name!r}")

        if not seg.key_components:
            # Should not happen if parser populated key_components
            return ValueType(current.type_name, is_collection=False)

        t = self._get_structured_type(current.type_name)
        if t.kind != "entity":
            raise SemanticError(
                f"Key predicates are only allowed on entity types, got {t.kind!r}"
            )

        if not t.key_properties:
            raise SemanticError(
                f"Entity type {t.name!r} has no key metadata; "
                "cannot apply key predicate"
            )

        expected_keys = list(t.key_properties)

        # Shape: positional vs named
        if len(seg.key_components) == 1 and seg.key_components[0].name is None:
            # Positional key: entity must have a single key property
            if len(expected_keys) != 1:
                raise SemanticError(
                    f"Positional key used on entity {t.name!r} "
                    f"with composite key {expected_keys!r}"
                )
            comps = [(expected_keys[0], seg.key_components[0].expr)]
        else:
            supplied_names = [kc.name for kc in seg.key_components]
            if any(name is None for name in supplied_names):
                raise SemanticError(
                    "Mixed positional/named key components are not allowed"
                )
            supplied_set = set(supplied_names)
            expected_set = set(expected_keys)
            if supplied_set != expected_set:
                raise SemanticError(
                    f"Key properties for {t.name!r} must be {sorted(expected_set)!r}, "
                    f"got {sorted(supplied_set)!r}"
                )
            comps = [(kc.name, kc.expr) for kc in seg.key_components]  # type: ignore[arg-type]

        # Type-check each component
        for key_name, expr in comps:
            assert key_name is not None
            prop = t.properties.get(key_name)
            if not prop:
                raise SemanticError(
                    f"{key_name!r} is not a structural property of {t.name!r}"
                )
            if prop.type.is_collection:
                raise SemanticError(
                    f"Key property {key_name!r} on {t.name!r} "
                    "cannot be collection-valued"
                )

            expected = ValueType(prop.type.name, is_collection=False)

            # Reuse existing literal coercion/type inference machinery
            if isinstance(expr, Literal):
                self._maybe_coerce_literal(expr, expected)
            else:
                expr_type = self._infer_expr_type(
                    expr, ValueType(t.name, is_collection=False), {}
                )
                if expr_type.is_collection:
                    raise SemanticError(
                        f"Key component {key_name!r} must be single-valued"
                    )
                if expr_type.type_name != expected.type_name:
                    raise SemanticError(
                        f"Key component {key_name!r} on {t.name!r} expects "
                        f"type {expected.type_name!r}, got {expr_type.type_name!r}"
                    )

        # Success: narrow from collection to singleton
        return ValueType(current.type_name, is_collection=False)

    def _resolve_segment(self, base: ValueType, seg: RGQLPathSegment) -> ValueType:
        t = self._get_structured_type(base.type_name)
        name = seg.name

        nav = t.nav_properties.get(name)
        if nav:
            vt = ValueType(
                nav.target_type.name,
                is_collection=nav.target_type.is_collection,
            )

            if seg.key_components is not None:
                vt = self._apply_key(vt, seg)
            elif seg.key_predicate is not None:
                # Backwards-compat simple behaviour
                if not vt.is_collection:
                    raise SemanticError(
                        "Key predicate not allowed on single-valued navigation:"
                        f" {name!r}"
                    )
                vt = ValueType(vt.type_name, is_collection=False)

            return vt

        prop = t.properties.get(name)
        if prop:
            if seg.key_predicate is not None or seg.key_components is not None:
                raise SemanticError(f"Key predicate not allowed on property {name!r}")
            return ValueType(prop.type.name, is_collection=prop.type.is_collection)

        # Simple type-cast segment
        if name in self.model.types:
            derived = self.model.get_type(name)
            if derived.kind not in ("entity", "complex"):
                raise SemanticError(
                    f"Type cast in path must target entity/complex type: {name!r}"
                )
            return ValueType(derived.name, is_collection=base.is_collection)

        # --------------------------------------------------------------
        # OData 4.01 key-as-segment support (single-key entities)
        #
        # If this segment didn't resolve as a property/navigation/type
        # and the current type is a *collection* of entities with a
        # single key property, interpret the segment as that key value
        # and feed it through the same _apply_key logic as paren-keys.
        # --------------------------------------------------------------
        if base.is_collection:
            et = self._get_structured_type(base.type_name)
            if et.kind == "entity" and et.key_properties:
                if len(et.key_properties) == 1:
                    key_name = et.key_properties[0]
                    prop = et.properties.get(key_name)
                    if not prop:
                        raise SemanticError(
                            f"Key property {key_name!r} not found on type {et.name!r}"
                        )
                    if prop.type.is_collection:
                        raise SemanticError(
                            f"Key property {key_name!r} on {et.name!r} "
                            "cannot be collection-valued"
                        )

                    edm_type_name = prop.type.name

                    # Build a synthetic key component:
                    # - for string keys, use the raw segment as a literal
                    # - for guid keys, parse the segment as a UUID
                    # - for other primitives (numeric, bool, etc.), parse
                    #   the segment as an expression.
                    if edm_type_name == "Edm.String":
                        expr = Literal(name)
                    elif edm_type_name == "Edm.Guid":
                        try:
                            expr = Literal(uuid.UUID(name))
                        except (ValueError, AttributeError) as exc:
                            raise SemanticError(
                                f"Segment {name!r} is not a valid key value for "
                                f"type {edm_type_name!r}: {exc}"
                            ) from exc
                    else:
                        try:
                            expr = parse_rgql_expr(name)
                        except ParseError as exc:
                            raise SemanticError(
                                f"Segment {name!r} is not a valid key value for "
                                f"type {edm_type_name!r}: {exc}"
                            ) from exc

                    synthetic = RGQLPathSegment(
                        name=seg.name,
                        key_predicate=None,
                        key_components=[KeyComponent(name=key_name, expr=expr)],
                        is_count=False,
                    )
                    return self._apply_key(base, synthetic)

                # Composite keys: we *do not* guess mapping from segments
                # to key components here. Use parentheses form:
                #   /OrderItems(OrderId=1,ProductId=2)
                # Fall through to error below.

        raise SemanticError(
            f"Unknown property/navigation '{name}' on type {base.type_name!r}"
        )

    def _get_structured_type(self, type_name: str) -> EdmType:
        t = self.model.try_get_type(type_name)
        if not t or t.kind not in ("entity", "complex"):
            raise SemanticError(f"Type {type_name!r} is not a structured type")
        return t

    # ------------------------------------------------------------------
    # Parameter aliases
    # ------------------------------------------------------------------

    def _build_alias_env(
        self, base_type: ValueType, q: RGQLQueryOptions
    ) -> Dict[str, ValueType]:
        """
        Infer types for parameter aliases defined in the query string.

        Example:
          ?$filter=Price gt @p1&@p1=10

        We infer the type of @p1 based on its literal/expr value.
        """
        env: Dict[str, ValueType] = {}
        for name, expr in q.param_aliases.items():
            env[name] = self._infer_expr_type(expr, base_type, env)
        return env

    # ------------------------------------------------------------------
    # Query options
    # ------------------------------------------------------------------

    def _check_query_options(
        self,
        base_type: ValueType,
        q: RGQLQueryOptions,
        alias_env: Dict[str, ValueType],
    ) -> None:
        if q.filter is not None:
            self._check_filter_expr(q.filter, base_type, alias_env)

        if q.orderby:
            self._check_orderby(q.orderby, base_type, alias_env)

        if q.select:
            self._check_select(q.select, base_type)

        if q.expand:
            self._check_expand(q.expand, base_type, alias_env)

        if q.apply:
            self._check_apply(q.apply, base_type, alias_env)

        if q.compute:
            self._check_compute(q.compute, base_type, alias_env)

        if q.top is not None and q.top < 0:
            raise SemanticError("$top must be non-negative")

        if q.skip is not None and q.skip < 0:
            raise SemanticError("$skip must be non-negative")

    def _check_compute(
        self,
        computes: List[ComputeExpression],
        base_type: ValueType,
        alias_env: Dict[str, ValueType],
    ) -> None:
        """Type-check the ``$compute`` system query option.

        Each compute expression is validated against the base element
        type of the collection (or single entity) addressed by the
        resource path.  The result type is not currently tracked, but
        any type errors inside the expression are reported.
        """
        seen_aliases = set()
        for comp in computes:
            if comp.alias in seen_aliases:
                raise SemanticError(
                    f"Duplicate computed property alias {comp.alias!r} in $compute"
                )
            seen_aliases.add(comp.alias)
            # Ensure the compute expression itself is well-typed.
            _ = self._infer_expr_type(comp.expr, base_type, alias_env)

    # ------------------------------------------------------------------
    # $select
    # ------------------------------------------------------------------

    def _check_select(self, select: List[str], base_type: ValueType) -> None:
        for path in select:
            self._resolve_property_path(base_type, path)

    def _resolve_property_path(self, base_type: ValueType, path: str) -> ValueType:
        current = base_type
        parts = [p for p in path.split("/") if p]
        if not parts:
            raise SemanticError(f"Empty property path: {path!r}")

        for part in parts:
            t = self._get_structured_type(current.type_name)
            nav = t.nav_properties.get(part)
            if nav:
                current = ValueType(nav.target_type.name, nav.target_type.is_collection)
                continue
            prop = t.properties.get(part)
            if prop:
                current = ValueType(prop.type.name, prop.type.is_collection)
                continue
            raise SemanticError(
                f"Unknown property/navigation '{part}' in path {path!r} "
                f"on type {t.name!r}"
            )

        return current

    # ------------------------------------------------------------------
    # $expand
    # ------------------------------------------------------------------

    def _materialize_expand_items(
        self,
        expand: List[ExpandItem],
        base_type: ValueType,
    ) -> List[ExpandItem]:
        """Expand wildcard ``*`` items into concrete navigation paths.

        The returned list is a deep copy of ``expand`` with the same
        semantics, except that any item whose ``path`` is ``"*"``
        is replaced by one item per navigation property on the current
        type.  Nested ``expand`` lists are processed recursively using
        the target type of each navigation.
        """
        if not expand:
            return []

        result: List[ExpandItem] = []
        base_struct = self._get_structured_type(base_type.type_name)

        for item in expand:
            if item.path == "*":
                # Wildcard: generate one item per navigation property.
                for nav_name, nav in base_struct.nav_properties.items():
                    target_type = ValueType(
                        nav.target_type.name,
                        nav.target_type.is_collection,
                    )
                    nested_expand = (
                        self._materialize_expand_items(item.expand, target_type)
                        if item.expand
                        else None
                    )
                    result.append(
                        ExpandItem(
                            path=nav_name,
                            is_ref=item.is_ref,
                            filter=item.filter,
                            orderby=item.orderby,
                            select=item.select,
                            expand=nested_expand,
                            top=item.top,
                            skip=item.skip,
                            count=item.count,
                            search=item.search,
                            levels=item.levels,
                        )
                    )
            else:
                # Normal path: may include type-cast segments.
                target_type = self._resolve_expand_target_type(base_type, item.path)
                nested_expand = (
                    self._materialize_expand_items(item.expand, target_type)
                    if item.expand
                    else None
                )
                result.append(
                    ExpandItem(
                        path=item.path,
                        is_ref=item.is_ref,
                        filter=item.filter,
                        orderby=item.orderby,
                        select=item.select,
                        expand=nested_expand,
                        top=item.top,
                        skip=item.skip,
                        count=item.count,
                        search=item.search,
                        levels=item.levels,
                    )
                )

        return result

    def _resolve_expand_target_type(
        self,
        base_type: ValueType,
        path: str,
    ) -> ValueType:
        """Resolve an ``$expand`` path string to its target value type.

        The path is interpreted relative to ``base_type`` and may consist
        of navigation property segments and type-cast segments, e.g.::

            "Orders/NS.OnlineOrder/Customer"

        Any invalid segment raises :class:`SemanticError`.
        """
        current = base_type
        parts = [p for p in path.split("/") if p]
        if not parts:
            raise SemanticError(f"Empty path in $expand item: {path!r}")

        for part in parts:
            t = self._get_structured_type(current.type_name)

            # 1) Navigation property?
            nav = t.nav_properties.get(part)
            if nav is not None:
                current = ValueType(
                    nav.target_type.name,
                    nav.target_type.is_collection,
                )
                continue

            # 2) Type-cast segment?  Mirror _resolve_segment behaviour.
            if part in self.model.types:
                derived = self.model.get_type(part)
                if derived.kind not in ("entity", "complex"):
                    raise SemanticError(
                        "Type cast in $expand path must target entity/complex "
                        f"type: {part!r}"
                    )
                # Cast preserves collection-ness.
                current = ValueType(
                    derived.name,
                    is_collection=current.is_collection,
                )
                continue

            # Otherwise, nothing matched.
            raise SemanticError(
                f"$expand path {path!r}: '{part}' is not a navigation "
                f"property or type-cast on {t.name!r}"
            )

        return current

    def _check_expand(
        self,
        expand: List[ExpandItem],
        base_type: ValueType,
        alias_env: Dict[str, ValueType],
    ) -> None:
        # Normalize any wildcard '*' entries into concrete paths before
        # we walk and validate them.
        materialized = self._materialize_expand_items(expand, base_type)
        for item in materialized:
            self._check_expand_item(item, base_type, alias_env)

    def _check_expand_item(
        self,
        item: ExpandItem,
        base_type: ValueType,
        alias_env: Dict[str, ValueType],
    ) -> None:
        # At this point, wildcard '*' paths have been expanded away by
        # _materialize_expand_items, so item.path is always concrete.
        target_type = self._resolve_expand_target_type(base_type, item.path)

        if item.filter is not None:
            self._check_filter_expr(item.filter, target_type, alias_env)

        if item.orderby:
            self._check_orderby(item.orderby, target_type, alias_env)

        if item.select:
            self._check_select(item.select, target_type)

        if item.expand:
            self._check_expand(item.expand, target_type, alias_env)

        if item.top is not None and item.top < 0:
            raise SemanticError("$top in $expand must be non-negative")

        if item.skip is not None and item.skip < 0:
            raise SemanticError("$skip in $expand must be non-negative")

        if item.levels is not None:
            if isinstance(item.levels, int) and item.levels <= 0:
                raise SemanticError("$levels must be > 0 or 'max'")

    # ------------------------------------------------------------------
    # $orderby
    # ------------------------------------------------------------------

    def _check_orderby(
        self,
        orderby: List[OrderByItem],
        base_type: ValueType,
        alias_env: Dict[str, ValueType],
    ) -> None:
        prev_ctx = self._expr_context
        self._expr_context = "orderby"
        try:
            for item in orderby:
                expr_type = self._infer_expr_type(item.expr, base_type, alias_env)
                if expr_type.is_collection:
                    raise SemanticError(
                        "$orderby expression must be scalar, got collection-type"
                    )
        finally:
            self._expr_context = prev_ctx

    # ------------------------------------------------------------------
    # $filter
    # ------------------------------------------------------------------

    def _check_filter_expr(
        self,
        expr: Expr,
        base_type: ValueType,
        alias_env: Dict[str, ValueType],
    ) -> None:
        prev_ctx = self._expr_context
        self._expr_context = "filter"
        try:
            _ = self._infer_expr_type(expr, base_type, alias_env)
        finally:
            self._expr_context = prev_ctx

        if not is_boolean_expr(expr):
            raise SemanticError("$filter expression must be boolean")

    # ------------------------------------------------------------------
    # Expression type inference
    # ------------------------------------------------------------------

    # pylint: disable=too-many-locals
    # pylint: disable=too-many-return-statements
    # pylint: disable=too-many-branches
    # pylint: disable=too-many-statements
    def _infer_expr_type(
        self,
        expr: Expr,
        base_type: ValueType,
        env: Dict[str, ValueType],
    ) -> ValueType:
        # Literals ------------------------------------------------------
        if isinstance(expr, Literal):
            v = expr.value

            # JSON complex/collection literals are typed later based on context;
            # for now we give them a generic pseudo-type and validate shape
            # in _maybe_coerce_literal.
            if isinstance(v, dict):
                return ValueType("Json.Object")
            if isinstance(v, list):
                return ValueType("Json.Array")
            if v is None:
                return ValueType("Edm.Null")

            # Boolean.
            if isinstance(v, bool):
                return ValueType("Edm.Boolean")

            # Numeric.
            if isinstance(v, int):
                return ValueType("Edm.Int64")
            if isinstance(v, float):
                return ValueType("Edm.Double")
            if isinstance(v, decimal.Decimal):
                return ValueType("Edm.Decimal")

            # String.
            if isinstance(v, str):
                return ValueType("Edm.String")
            if isinstance(v, uuid.UUID):
                return ValueType("Edm.Guid")

            # Binary.
            if isinstance(v, (bytes, bytearray, memoryview)):
                return ValueType("Edm.Binary")

            # Temporal.
            if isinstance(v, datetime.datetime):
                return ValueType("Edm.DateTimeOffset")
            if isinstance(v, datetime.date):
                return ValueType("Edm.Date")
            if isinstance(v, datetime.time):
                return ValueType("Edm.TimeOfDay")
            if isinstance(v, datetime.timedelta):
                return ValueType("Edm.Duration")

            # Fallback.
            tname = type(v).__name__
            return ValueType(f"Python.{tname}")

        # Explicit enum literal
        if isinstance(expr, EnumLiteral):
            return ValueType(expr.type_name)

        # Spatial literal
        if isinstance(expr, SpatialLiteral):
            return ValueType("Edm.Geography" if expr.is_geography else "Edm.Geometry")

        # Identifiers ---------------------------------------------------
        if isinstance(expr, Identifier):
            # 1) Parameter alias or lambda variable?
            if expr.name in env:
                return env[expr.name]

            # 2) Then fall back to properties/navs on the base type
            t = self._get_structured_type(base_type.type_name)
            prop = t.properties.get(expr.name)
            if prop:
                # Enforce filter/sort capabilities
                if self._expr_context == "filter" and not prop.filterable:
                    raise SemanticError(
                        f"Property {expr.name!r} on {t.name!r} is not filterable"
                    )
                if self._expr_context == "orderby" and not prop.sortable:
                    raise SemanticError(
                        f"Property {expr.name!r} on {t.name!r} is not sortable"
                    )
                return ValueType(prop.type.name, prop.type.is_collection)

            nav = t.nav_properties.get(expr.name)
            if nav:
                return ValueType(nav.target_type.name, nav.target_type.is_collection)

            raise SemanticError(
                f"Unknown identifier '{expr.name}' on type {base_type.type_name!r}"
            )

        # Member access -------------------------------------------------
        if isinstance(expr, MemberAccess):
            base_t = self._infer_expr_type(expr.base, base_type, env)
            t = self.model.try_get_type(base_t.type_name)
            if not t or t.kind not in ("entity", "complex"):
                raise SemanticError(
                    f"Cannot access member {expr.member!r} on non-structured type "
                    f"{base_t.type_name!r}"
                )

            prop = t.properties.get(expr.member)
            if prop:
                if self._expr_context == "filter" and not prop.filterable:
                    raise SemanticError(
                        f"Property {expr.member!r} on {t.name!r} is not filterable"
                    )
                if self._expr_context == "orderby" and not prop.sortable:
                    raise SemanticError(
                        f"Property {expr.member!r} on {t.name!r} is not sortable"
                    )
                return ValueType(prop.type.name, prop.type.is_collection)

            nav = t.nav_properties.get(expr.member)
            if nav:
                return ValueType(nav.target_type.name, nav.target_type.is_collection)

            raise SemanticError(
                f"{expr.member!r} is not a property or navigation on {t.name!r}"
            )

        # Unary op ------------------------------------------------------
        if isinstance(expr, UnaryOp):
            inner_t = self._infer_expr_type(expr.operand, base_type, env)
            return inner_t

        # Binary op -----------------------------------------------------
        if isinstance(expr, BinaryOp):
            left_t = self._infer_expr_type(expr.left, base_type, env)
            right_t = self._infer_expr_type(expr.right, base_type, env)
            op = expr.op

            if op in {"and", "or"}:
                return ValueType("Edm.Boolean")

            # OData 4.01 "in" operator
            if op == "in":
                # Left operand MUST be a single value
                if left_t.is_collection:
                    raise SemanticError(
                        "Left operand of 'in' must be a single value, not a collection"
                    )

                # Case 1: right-hand side is a collection-valued expression
                if right_t.is_collection:
                    elem_t = right_t.element()

                    # Basic type compatibility: same element type, ignoring Edm.Null
                    if (
                        left_t.type_name != elem_t.type_name
                        and left_t.type_name != "Edm.Null"
                        and elem_t.type_name != "Edm.Null"
                    ):
                        raise SemanticError(
                            "Type mismatch for 'in' operator: left operand is "
                            f"{left_t.type_name!r} but right-hand collection "
                            f"has elements of {elem_t.type_name!r}"
                        )

                    return ValueType("Edm.Boolean")

                # Case 2: right-hand side is a literal list from JSON array or in(...)
                if isinstance(expr.right, Literal) and isinstance(
                    expr.right.value, list
                ):
                    for idx, elem in enumerate(expr.right.value):
                        # Only primitive / enum-like elements allowed here
                        if isinstance(elem, (dict, list)):
                            raise SemanticError(
                                "Right-hand side of 'in' must be a collection of "
                                "primitive or enum values; "
                                f"element #{idx} is itself a collection or object"
                            )

                        # Reuse existing literal/type rules for each element
                        self._maybe_coerce_literal(Literal(elem), left_t)

                    return ValueType("Edm.Boolean")

                # Anything else is invalid: 'in' requires a collection or list of values
                raise SemanticError(
                    "Right operand of 'in' must be a collection-valued expression "
                    "or a list literal"
                )

            if op in {"eq", "ne", "gt", "ge", "lt", "le", "has"}:
                # Try to interpret literals (JSON, strings) according to the other side's type.
                if isinstance(expr.left, Literal):
                    self._maybe_coerce_literal(expr.left, right_t)
                if isinstance(expr.right, Literal):
                    self._maybe_coerce_literal(expr.right, left_t)

                if op == "has":
                    self._ensure_enum_for_has(left_t)

                return ValueType("Edm.Boolean")

            if op in {"add", "sub", "mul", "div", "mod"}:
                # We don't yet implement numeric promotion; just return left side.
                return left_t

            return left_t

        # Function Call -------------------------------------------------
        if isinstance(expr, FunctionCall):
            name_lower = expr.name.lower()
            if name_lower in {"length", "indexof", "year", "month", "day"}:
                return ValueType("Edm.Int32")
            if name_lower in {"tolower", "toupper", "trim", "concat"}:
                return ValueType("Edm.String")
            if name_lower in {"contains", "startswith", "endswith"}:
                if len(expr.args) != 2:
                    raise SemanticError(
                        f"{expr.name}() expects exactly 2 arguments"
                    )
                prop_expr, needle_expr = expr.args
                if not isinstance(prop_expr, (Identifier, MemberAccess)):
                    raise SemanticError(
                        f"{expr.name}() first argument must be a property path"
                    )

                prop_t = self._infer_expr_type(prop_expr, base_type, env)
                if prop_t.is_collection or prop_t.type_name != "Edm.String":
                    raise SemanticError(
                        f"{expr.name}() first argument must be Edm.String"
                    )

                needle_t = self._infer_expr_type(needle_expr, base_type, env)
                if needle_t.is_collection or needle_t.type_name != "Edm.String":
                    raise SemanticError(
                        f"{expr.name}() second argument must be Edm.String"
                    )
                return ValueType("Edm.Boolean")
            if expr.args:
                return self._infer_expr_type(expr.args[0], base_type, env)
            return ValueType("Edm.Null")

        # Lambda any/all -----------------------------------------------
        if isinstance(expr, LambdaCall):
            src_t = self._infer_expr_type(expr.source, base_type, env)
            if not src_t.is_collection:
                raise SemanticError(
                    f"Lambda source for {expr.kind} must be a collection, got {src_t}"
                )
            elem_t = ValueType(src_t.type_name, is_collection=False)
            new_env = dict(env)
            if expr.var:
                new_env[expr.var] = elem_t
            if expr.predicate is None:
                return ValueType("Edm.Boolean")
            _ = self._infer_expr_type(expr.predicate, elem_t, new_env)
            return ValueType("Edm.Boolean")

        # Type functions ------------------------------------------------
        if isinstance(expr, CastExpr):
            return ValueType(expr.type_ref.full_name, is_collection=False)

        if isinstance(expr, IsOfExpr):
            return ValueType("Edm.Boolean")

        raise SemanticError(f"Unsupported expression node for type inference: {expr!r}")

    # ------------------------------------------------------------------
    # Literal coercion helpers (JSON + enums + primitive sanity)
    # ------------------------------------------------------------------

    def _maybe_coerce_literal(self, lit_expr: Literal, expected: ValueType) -> None:
        """
        Interpret a Literal according to the expected type, raising if incompatible.

        - JSON dict/list values are validated against complex/collection types.
        - String values are validated against enum types, if metadata is available.
        - Simple primitive compatibility checks for common Edm.* types.
        """
        v = lit_expr.value

        # JSON -> complex/collection, except for Edm.Untyped
        if isinstance(v, (dict, list)):
            if expected.type_name == "Edm.Untyped":
                # Edm.Untyped is allowed to take arbitrary JSON without shape checks
                return
            self._check_json_literal_against_type(v, expected)
            return

        # String -> enum or Edm.String (otherwise fall through to primitive checks)
        if isinstance(v, str):
            t = self.model.try_get_type(expected.type_name)
            if t and t.kind == "enum":
                self._check_enum_literal(v, t)
                return
            if expected.type_name == "Edm.String":
                # Any string is fine for Edm.String
                return
            # else: e.g. Edm.Guid, Edm.Int32, etc.; fall through to primitive checks

        # Primitive sanity: check a few key EDM primitives
        self._check_primitive_literal_against_type(v, expected)

    def _check_primitive_literal_against_type(
        self, value: Any, expected: ValueType
    ) -> None:
        """
        Very lightweight primitive-compatibility checks.

        We don't fully implement EDM promotion rules; we just catch obvious
        nonsense, like comparing an Edm.Boolean property to a JSON object.
        """
        name = expected.type_name

        if not name.startswith("Edm."):
            return

        # Null literal is always allowed at this level; nullability is checked elsewhere.
        if value is None:
            return

        if name == "Edm.Boolean":
            if not isinstance(value, bool):
                raise SemanticError("Boolean comparison must use boolean literals")

        # String --------------------------------------------------------
        if name == "Edm.String":
            if not isinstance(value, str):
                raise SemanticError("String comparison must use string literals")

        # Binary --------------------------------------------------------
        if name == "Edm.Binary":
            if not isinstance(value, (bytes, bytearray, memoryview)):
                raise SemanticError(
                    "Binary comparison must use binary'...' or x'...' literals"
                )

        # Guid --------------------------------------------------------
        if name == "Edm.Guid":
            # Allow null; nullability is handled elsewhere.
            if not isinstance(value, uuid.UUID):
                raise SemanticError("Guid comparison must use guid'...' literals")

        # Stream --------------------------------------------------------
        if name == "Edm.Stream":
            # No literal form; any attempt to use a stream literal is invalid.
            raise SemanticError("Edm.Stream values cannot be used as literals")

        # Temporal primitives -------------------------------------------
        if name == "Edm.DateTimeOffset":
            if not isinstance(value, datetime.datetime):
                raise SemanticError(
                    "DateTimeOffset comparison must use datetimeoffset'...' literals"
                )

        if name == "Edm.Date":
            # Allow date but reject datetime (even though it's a subclass of date)
            if not isinstance(value, datetime.date) or isinstance(
                value, datetime.datetime
            ):
                raise SemanticError("Date comparison must use date'...' literals")

        if name == "Edm.TimeOfDay":
            if not isinstance(value, datetime.time):
                raise SemanticError(
                    "TimeOfDay comparison must use timeofday'...' literals"
                )

        if name == "Edm.Duration":
            if not isinstance(value, datetime.timedelta):
                raise SemanticError(
                    "Duration comparison must use duration'...' or ISO 8601 "
                    "duration literals"
                )

        # Numeric primitives -------------------------------------------
        numeric_types = {
            "Edm.Byte",
            "Edm.SByte",
            "Edm.Int16",
            "Edm.Int32",
            "Edm.Int64",
            "Edm.Decimal",
            "Edm.Single",
            "Edm.Double",
        }
        if name in numeric_types:
            if not isinstance(value, (int, float, bool, decimal.Decimal)):
                raise SemanticError(
                    f"Numeric comparison with {name} expects numeric literal, "
                    f"got {type(value).__name__}"
                )

            # Range checks for integer types
            if isinstance(value, bool):
                # Treat True/False as 1/0 if you want to allow bools here;
                # alternatively, forbid them.
                int_value = int(value)
            else:
                int_value = value if isinstance(value, int) else None

            if name == "Edm.Byte" and int_value is not None:
                if not 0 <= int_value <= 255:
                    raise SemanticError("Edm.Byte literal out of range [0, 255]")

            if name == "Edm.SByte" and int_value is not None:
                if not -128 <= int_value <= 127:
                    raise SemanticError("Edm.SByte literal out of range [-128, 127]")

            if name == "Edm.Int16" and int_value is not None:
                if not -32768 <= int_value <= 32767:
                    raise SemanticError("Edm.Int16 literal out of range")

            if name == "Edm.Int32" and int_value is not None:
                if not -(2**31) <= int_value <= 2**31 - 1:
                    raise SemanticError("Edm.Int32 literal out of range")

            if name == "Edm.Int64" and int_value is not None:
                if not -(2**63) <= int_value <= 2**63 - 1:
                    raise SemanticError("Edm.Int64 literal out of range")

            # Edm.Decimal, Edm.Single, Edm.Double are constrained primarily
            # by facets and backend; you can treat any finite number as ok
            # here and let the backend enforce precision/scale.

        # Spatial primitives --------------------------------------------
        spatial_roots = {"Edm.Geography", "Edm.Geometry"}
        if (
            name in spatial_roots
            or name.startswith("Edm.Geography")
            or name.startswith("Edm.Geometry")
        ):
            # At this layer, your Literal is a SpatialLiteral, not a Python
            # primitive. _maybe_coerce_literal only receives primitive
            # values, so value should not be a SpatialLiteral. If it is,
            # that's a bug in the caller.
            return

        # Untyped --------------------------------------------------------
        if name == "Edm.Untyped":
            # By definition, any JSON value is allowed; no checks here.
            return

        # For other primitives, we rely on the literal parser.

    def _check_enum_literal(self, value: str, enum_type: EdmType) -> None:
        """
        Check that a string literal used as an enum value is compatible
        with the given EDM enum type.

        - Supports comma-separated flags: "Red,Green".
        - If enum_type.enum_members is empty, we don't enforce names.
        """
        parts = [p.strip() for p in value.split(",") if p.strip()]
        if not enum_type.enum_members:
            return

        for p in parts:
            if p not in enum_type.enum_members:
                raise SemanticError(
                    f"Invalid enum literal {value!r} for enum {enum_type.name!r}: "
                    f"member {p!r} is not defined"
                )

    def _check_json_literal_against_type(self, value: Any, expected: ValueType) -> None:
        """
        Validate a JSON literal (dict/list) against an expected EDM type:

          - Complex / entity type
          - Collection of complex/entity type

        We only check structure and property names – not full primitive
        type compatibility.
        """
        t = self.model.try_get_type(expected.type_name)
        if not t or t.kind not in ("complex", "entity"):
            raise SemanticError(
                "JSON literal not allowed for non-structured type"
                f" {expected.type_name!r}"
            )

        if expected.is_collection:
            if not isinstance(value, list):
                raise SemanticError(
                    f"JSON literal for collection of {t.name!r} must be a JSON array"
                )
            for idx, elem in enumerate(value):
                if not isinstance(elem, dict):
                    raise SemanticError(
                        f"Element #{idx} in JSON array must be an object "
                        f"for collection of {t.name!r}"
                    )
                self._check_json_object_against_structured_type(elem, t)
        else:
            if not isinstance(value, dict):
                raise SemanticError(
                    f"JSON literal for {t.name!r} must be a JSON object"
                )
            self._check_json_object_against_structured_type(value, t)

    def _check_json_object_against_structured_type(self, obj: dict, t: EdmType) -> None:
        """
        Check that JSON object keys match defined structural properties.
        For complex/entity literal we only allow structural properties,
        not navigation props.
        """
        for key, val in obj.items():
            prop = t.properties.get(key)
            if not prop:
                raise SemanticError(
                    f"Property {key!r} is not defined on structured type {t.name!r}"
                )

            pt = self.model.try_get_type(prop.type.name)
            if pt and pt.kind in ("complex", "entity"):
                expected_vt = ValueType(
                    prop.type.name, is_collection=prop.type.is_collection
                )
                self._check_json_literal_against_type(val, expected_vt)

    def _ensure_enum_for_has(self, left_t: ValueType) -> None:
        """
        For the 'has' operator, ensure the left-hand side is an enum type,
        if we can resolve it.
        """
        t = self.model.try_get_type(left_t.type_name)
        if t and t.kind != "enum":
            raise SemanticError(
                "'has' operator requires enum type on left side, got"
                f" {left_t.type_name!r}"
            )

    # ------------------------------------------------------------------
    # $apply
    # ------------------------------------------------------------------

    def _check_apply(
        self,
        transforms: List[ApplyNode],
        base_type: ValueType,
        alias_env: Dict[str, ValueType],
    ) -> None:
        current_type = base_type
        for t in transforms:
            current_type = self._check_apply_transform(t, current_type, alias_env)

    def _check_apply_transform(
        self,
        t: ApplyNode,
        current: ValueType,
        alias_env: Dict[str, ValueType],
    ) -> ValueType:
        if isinstance(t, FilterTransform):
            self._check_filter_expr(t.predicate, current, alias_env)
            return current

        if isinstance(t, OrderByTransform):
            self._check_orderby(t.items, current, alias_env)
            return current

        if isinstance(t, SearchTransform):
            return current

        if isinstance(t, SkipTransform):
            if t.count < 0:
                raise SemanticError("skip(...) in $apply must be non-negative")
            return current

        if isinstance(t, TopTransform):
            if t.count < 0:
                raise SemanticError("top(...) in $apply must be non-negative")
            return current

        if isinstance(t, IdentityTransform):
            return current

        if isinstance(t, ComputeTransform):
            for comp in t.computes:
                _ = self._infer_expr_type(comp.expr, current, alias_env)
            return current

        if isinstance(t, AggregateTransform):
            for agg in t.aggregates:
                if agg.is_count:
                    continue
                if agg.expr is None:
                    raise SemanticError("Non-$count aggregate requires an expression")
                et = self._infer_expr_type(agg.expr, current, alias_env)
                if et.is_collection:
                    raise SemanticError(
                        "Aggregate expression must be scalar, got collection"
                    )
            return current

        if isinstance(t, GroupByTransform):
            for path in t.grouping_paths:
                self._resolve_property_path(current, path)
            if t.sub_transforms:
                self._check_apply(t.sub_transforms, current, alias_env)
            return current

        if isinstance(t, BottomTopTransform):
            _ = self._infer_expr_type(t.n_expr, current, alias_env)
            _ = self._infer_expr_type(t.value_expr, current, alias_env)
            return current

        if isinstance(t, ConcatTransform):
            for seq in t.sequences:
                self._check_apply(seq, current, alias_env)
            return current

        if isinstance(t, CustomApplyTransform):
            return current

        raise SemanticError(f"Unknown $apply transform node: {t!r}")

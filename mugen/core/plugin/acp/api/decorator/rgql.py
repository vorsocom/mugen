"""Defines utility decorators for RGQL-enabled API endpoints."""

import uuid
from dataclasses import dataclass, fields
from functools import wraps
from types import SimpleNamespace
from typing import Any, Callable, Sequence

from quart import abort, current_app, request
from sqlalchemy.exc import SQLAlchemyError

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    OrderClause,
    RelatedPathHop,
    RelatedTextFilter,
    TextFilter,
    TextFilterOp,
)
from mugen.core.plugin.acp.contract.service.authorization import IAuthorizationService
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.acp.utility.rgql.nav_filter_planner import plan_related_path
from mugen.core.plugin.acp.utility.rgql.default_where import (
    make_default_where_provider,
)
from mugen.core.utility.string.case_conversion_helper import (
    snake_to_title,
    title_to_snake,
)
from mugen.core.utility.rgql import ParseError as RGQLParseError
from mugen.core.utility.rgql import parse_rgql_url, RGQLQueryOptions, SemanticChecker
from mugen.core.utility.rgql import SemanticError as RGQLSemanticError
from mugen.core.utility.rgql.model import EdmType
from mugen.core.utility.rgql.search_parser import (
    SearchBinary,
    SearchExpr,
    SearchNot,
    SearchTerm,
)
from mugen.core.gateway.storage.rdbms.rgql_adapter.error import RGQLExpandError
from mugen.core.gateway.storage.rdbms.rgql_adapter.rgql_expand import (
    apply_to_filter_groups,
    apply_to_where,
    ExpansionContext,
    expand_navs_bulk,
    normalise_expand_levels,
)
from mugen.core.gateway.storage.rdbms.rgql_adapter.rgql_to_relational import (
    RGQLToRelationalAdapter,
)

# pylint: disable=too-many-statements
# pylint: disable=too-many-arguments

_EDM_TENANT = "ACP.Tenant"
_EDM_TENANT_MEMBERSHIP = "ACP.TenantMembership"
_EDM_USER = "ACP.User"
_NAV_TENANT = "Tenant"
_NAV_TENANT_MEMBERSHIPS = "TenantMemberships"
_SELF_TENANT_DISCOVERY_FIELDS = {
    _EDM_TENANT_MEMBERSHIP: frozenset({"tenant_id", "status", "tenant"}),
    _EDM_TENANT: frozenset({"id", "name", "slug"}),
}

PathPlanner = Callable[[str], tuple[Sequence[RelatedPathHop], str] | None]


@dataclass
class _SelfTenantDiscoveryState:
    """Tracks whether this request is using the self tenant discovery exception."""

    enabled: bool = False


def _merge_filter_groups(
    left: FilterGroup,
    right: FilterGroup,
) -> FilterGroup:
    """Merge two conjunctive filter groups into one."""
    where = dict(left.where)
    for key, value in right.where.items():
        if key in where and where[key] != value:
            raise ValueError(f"Conflicting equality predicates for column {key!r}")
        where[key] = value

    return FilterGroup(
        where=where,
        text_filters=[*left.text_filters, *right.text_filters],
        scalar_filters=[*left.scalar_filters, *right.scalar_filters],
        related_text_filters=[
            *left.related_text_filters,
            *right.related_text_filters,
        ],
        related_scalar_filters=[
            *left.related_scalar_filters,
            *right.related_scalar_filters,
        ],
    )


def _and_filter_groups(
    left: Sequence[FilterGroup] | None,
    right: Sequence[FilterGroup] | None,
) -> list[FilterGroup]:
    """Combine two DNF filter group sets with logical AND."""
    if not left:
        return list(right or [])

    if not right:
        return list(left)

    return [
        _merge_filter_groups(left_group, right_group)
        for left_group in left
        for right_group in right
    ]


def _search_term_filter_groups(
    term: SearchTerm,
    *,
    search_fields: Sequence[str],
    edm_type: EdmType,
    path_planner: PathPlanner,
) -> list[FilterGroup]:
    """Build OR filter groups for a single configured search term."""
    groups: list[FilterGroup] = []
    for field in search_fields:
        path_plan = path_planner(field)
        if path_plan is None:
            if "/" in field or field not in edm_type.properties:
                raise ValueError(f"Unknown $search field {field!r}.")

            groups.append(
                FilterGroup(
                    text_filters=[
                        TextFilter(
                            field=title_to_snake(field),
                            op=TextFilterOp.CONTAINS,
                            value=term.text,
                            case_sensitive=False,
                        )
                    ]
                )
            )
            continue

        hops, terminal_col = path_plan
        groups.append(
            FilterGroup(
                related_text_filters=[
                    RelatedTextFilter(
                        path_hops=list(hops),
                        field=terminal_col,
                        op=TextFilterOp.CONTAINS,
                        value=term.text,
                        case_sensitive=False,
                    )
                ]
            )
        )

    return groups


def _search_filter_groups(
    expr: SearchExpr,
    *,
    search_fields: Sequence[str],
    edm_type: EdmType,
    path_planner: PathPlanner,
) -> list[FilterGroup]:
    """Translate a configured RGQL $search AST to DNF filter groups."""
    if isinstance(expr, SearchTerm):
        return _search_term_filter_groups(
            expr,
            search_fields=search_fields,
            edm_type=edm_type,
            path_planner=path_planner,
        )

    if isinstance(expr, SearchBinary):
        left = _search_filter_groups(
            expr.left,
            search_fields=search_fields,
            edm_type=edm_type,
            path_planner=path_planner,
        )
        right = _search_filter_groups(
            expr.right,
            search_fields=search_fields,
            edm_type=edm_type,
            path_planner=path_planner,
        )
        if expr.op == "or":
            return [*left, *right]
        if expr.op == "and":
            return _and_filter_groups(left, right)

    if isinstance(expr, SearchNot):
        raise ValueError("$search not expressions are not supported.")

    raise ValueError(f"Unsupported $search expression: {expr!r}")


def _config_provider():
    return di.container.config


def _logger_provider():
    return di.container.logging_gateway


def _auth_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_SVC_AUTH)


def _registry_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_REGISTRY)


def rgql_enabled(
    _fn=None,
    *,
    tenant_kw: str | None = None,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
    auth_provider=_auth_provider,
    registry_provider=_registry_provider,
):
    """
    Enable RGQL/OData-style query options ($filter/$orderby/$top/$skip/$select/$expand
    /$count) for an endpoint bound to a given EDM entity type and entity set.
    """

    def decorator(func):
        # pylint: disable=too-many-locals
        # pylint: disable=too-many-branches
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config: SimpleNamespace = config_provider()
            _logger: ILoggingGateway = logger_provider()
            auth_svc: IAuthorizationService = auth_provider()
            registry: IAdminRegistry = registry_provider()

            entity_set: str = kwargs.get("entity_set")
            entity_id: str = kwargs.get("entity_id")

            if entity_set not in registry.schema_index:
                abort(404)

            resource = registry.get_resource(entity_set)
            if not resource.behavior.rgql_enabled:
                abort(403)

            tenant_id = None
            if tenant_kw:
                raw = kwargs.get(tenant_kw)
                if raw is None:
                    abort(400, f"Missing required path parameter: {tenant_kw}.")

                try:
                    tenant_id = uuid.UUID(str(raw))
                except ValueError:
                    abort(400, f"Invalid UUID for path parameter: {tenant_kw}.")

            auth_user = kwargs.get("auth_user")
            if auth_user is None:
                abort(400, "Missing required path parameter: auth_user.")

            try:
                auth_user_id = uuid.UUID(str(auth_user))
            except ValueError:
                abort(400, "Invalid UUID for path parameter: auth_user.")

            is_current_user_entity_request = False
            if entity_set == "Users" and entity_id is not None:
                try:
                    is_current_user_entity_request = (
                        uuid.UUID(str(entity_id)) == auth_user_id
                    )
                except ValueError:
                    # Entity ID validation is handled below on the entity path.
                    is_current_user_entity_request = False

            allow_global_admin = kwargs.get("allow_global_admin")
            if allow_global_admin is None:
                allow_global_admin = False

            self_tenant_discovery = _SelfTenantDiscoveryState()

            # --- helpers ---
            base_default_where_provider = make_default_where_provider(
                registry=registry,
                tenant_id=tenant_id,
            )

            def default_where_provider(type_name: str) -> dict[str, Any]:
                defaults = dict(base_default_where_provider(type_name))
                if (
                    self_tenant_discovery.enabled
                    and type_name == _EDM_TENANT_MEMBERSHIP
                ):
                    defaults["status"] = "active"
                return defaults

            def _serialize_entity(
                entity,
                edm_type: EdmType,
                columns: Sequence[str] | None,
                expand_paths: set[str],
            ) -> dict[str, Any]:
                out: dict[str, Any] = {}
                for f in fields(entity):
                    v = getattr(entity, f.name)
                    if v is None:
                        continue
                    discovery_fields = None
                    if self_tenant_discovery.enabled:
                        discovery_fields = _SELF_TENANT_DISCOVERY_FIELDS.get(
                            edm_type.name
                        )
                    if discovery_fields is not None and f.name not in discovery_fields:
                        continue
                    title = snake_to_title(f.name)
                    if edm_type.property_redacted(title):
                        continue
                    if columns is None or f.name in columns or title in expand_paths:
                        out[title] = v
                return out

            def _self_tenant_discovery_path_permitted(
                edm_type: EdmType,
                path: str,
            ) -> bool:
                if not is_current_user_entity_request:
                    return False

                if edm_type.name == _EDM_USER and path == _NAV_TENANT_MEMBERSHIPS:
                    self_tenant_discovery.enabled = True
                    return True

                if (
                    self_tenant_discovery.enabled
                    and edm_type.name == _EDM_TENANT_MEMBERSHIP
                    and path == _NAV_TENANT
                ):
                    return True

                return False

            async def _resource_path_permitted(
                edm_type: EdmType,
                path: str,
            ) -> bool:
                """Determine if a user is permitted to access the given
                resource path."""
                nav_property = edm_type.nav_properties.get(path)
                if nav_property is None:
                    return False

                namespace = registry.get_resource_by_type(edm_type.name).namespace
                ns = AdminNs(namespace)

                tname = nav_property.target_type.name or ""
                leaf = tname.split(".", 1)[1] if "." in tname else tname

                perm_obj = ns.obj(title_to_snake(leaf))
                perm_type = ns.verb("read")

                permitted = await auth_svc.has_permission(
                    user_id=auth_user_id,
                    permission_object=perm_obj,
                    permission_type=perm_type,
                    tenant_id=tenant_id,
                    allow_global_admin=allow_global_admin,
                )
                if permitted:
                    return True

                return _self_tenant_discovery_path_permitted(edm_type, path)

            admin_edm_schema = registry.schema
            semantic_checker = SemanticChecker(model=admin_edm_schema)
            edm_type = admin_edm_schema.get_type(registry.schema_index[entity_set])

            rgql_url = None
            raw_qs = (
                request.query_string.decode("utf-8") if request.query_string else ""
            )

            if raw_qs:
                synthetic_url = (
                    f"/{entity_set}?{raw_qs}"
                    if entity_id is None
                    else f"/{entity_set}/{entity_id}?{raw_qs}"
                )
                try:
                    rgql_url = parse_rgql_url(synthetic_url)
                    semantic_checker.check_url(rgql_url)
                except (RGQLParseError, RGQLSemanticError) as exc:
                    current_app.logger.debug(
                        f"Invalid RGQL query on {entity_set}: {exc}"
                    )
                    abort(400, "Invalid RGQL query.")

            opts: RGQLQueryOptions | None = None
            query_columns: list[str] | None = None
            response_columns: list[str] | None = None
            filter_groups: Sequence[FilterGroup] | None = None
            order_by: Sequence[OrderClause] | None = None
            limit: int | None = None
            offset: int | None = None
            expand_paths: set[str] = set()

            # RGQL safety limits.
            default_top = getattr(config.acp, "rgql_default_top", 100)
            max_top = getattr(config.acp, "rgql_max_top", 500)
            max_skip = getattr(config.acp, "rgql_max_skip", 10_000)

            max_select = getattr(config.acp, "rgql_max_select", 50)
            max_orderby = getattr(config.acp, "rgql_max_orderby", 5)
            max_expand_paths = getattr(config.acp, "rgql_max_expand_paths", 10)

            allow_expand_wildcard = getattr(
                config.acp,
                "rgql_allow_expand_wildcard",
                False,
            )

            max_filter_terms = getattr(config.acp, "rgql_max_filter_terms", 25)
            max_filter_nav_depth = getattr(config.acp, "rgql_max_filter_nav_depth", 4)

            max_depth = (
                resource.behavior.rgql_max_expand_depth
                if resource.behavior.rgql_max_expand_depth is not None
                else getattr(config.acp, "rgql_max_expand_depth", 3)
            )

            table_name_cache: dict[str, str] = {}

            def _table_name_for_edm_type(edm_type_name: str) -> str:
                if edm_type_name in table_name_cache:
                    return table_name_cache[edm_type_name]

                target_resource = registry.get_resource_by_type(edm_type_name)
                target_service = registry.get_edm_service(target_resource.service_key)
                table_name = getattr(target_service, "table", None)
                if not table_name:
                    raise ValueError(
                        f"No logical table name found for EDM type {edm_type_name!r}."
                    )
                table_name_cache[edm_type_name] = table_name
                return table_name

            def _plan_nav_path(
                base_type_name: str,
                prop_path: str,
            ) -> tuple[list[RelatedPathHop], str] | None:
                return plan_related_path(
                    base_type_name=base_type_name,
                    prop_path=prop_path,
                    model=admin_edm_schema,
                    table_resolver=_table_name_for_edm_type,
                    max_nav_depth=max_filter_nav_depth,
                )

            adapter: RGQLToRelationalAdapter = RGQLToRelationalAdapter()
            ctx: ExpansionContext = None
            if rgql_url is not None:
                opts = rgql_url.query

                if opts.select:
                    if len(opts.select) > max_select:
                        abort(400, f"Max $select ({max_select}) exceeded.")

                    response_columns = [
                        title_to_snake(p) for p in opts.select if "/" not in p
                    ]

                query_columns = (
                    response_columns[:] if response_columns is not None else None
                )

                # Ensure query columns include join keys required to materialize
                # any $expand, even when the client uses $select to omit them.
                if (
                    opts is not None
                    and isinstance(opts.expand, list)
                    and opts.expand
                    and query_columns is not None
                ):
                    required_cols: set[str] = {"id"}
                    for exp in opts.expand:
                        nav_name = exp.path.split("/", 1)[0]
                        try:
                            nav_prop = edm_type.nav_properties[nav_name]
                        except KeyError:
                            nav_prop = None
                        if (
                            nav_prop is not None
                            and not nav_prop.target_type.is_collection
                        ):
                            required_cols.add(title_to_snake(nav_prop.source_fk))
                    for col in required_cols:
                        if col not in query_columns:
                            query_columns.append(col)

                if entity_id is None:
                    try:
                        filter_groups, order_by, limit, offset = (
                            adapter.build_relational_query(
                                opts,
                                path_planner=lambda path: _plan_nav_path(
                                    edm_type.name, path
                                ),
                            )
                        )
                    except ValueError as exc:
                        abort(400, str(exc))

                    search_fields = tuple(
                        getattr(resource.behavior, "search_fields", ()) or ()
                    )
                    search_expr = getattr(opts, "search", None)
                    if search_expr is not None and search_fields:
                        try:
                            search_filter_groups = _search_filter_groups(
                                search_expr,
                                search_fields=search_fields,
                                edm_type=edm_type,
                                path_planner=lambda path: _plan_nav_path(
                                    edm_type.name, path
                                ),
                            )
                            filter_groups = _and_filter_groups(
                                filter_groups,
                                search_filter_groups,
                            )
                        except ValueError as exc:
                            abort(400, str(exc))

                    if order_by and len(order_by) > max_orderby:
                        abort(400, f"Max $orderby ({max_orderby}) exceeded.")

                    if limit is None:
                        limit = default_top

                    if limit > max_top:
                        abort(400, f"$top exceeds max ({max_top}).")

                    if offset is None:
                        offset = 0

                    if offset > max_skip:
                        abort(400, f"$skip exceeds max ({max_skip}).")

                ctx = ExpansionContext(
                    model=admin_edm_schema,
                    adapter=adapter,
                    serialization_provider=_serialize_entity,
                    service_resolver=lambda edm_type_name: registry.get_edm_service(
                        registry.get_resource_by_type(edm_type_name).service_key,
                    ),
                    path_permission_provider=_resource_path_permitted,
                    max_depth=max_depth,
                    allow_expand_wildcard=allow_expand_wildcard,
                    default_top=default_top,
                    max_top=max_top,
                    max_skip=max_skip,
                    max_select=max_select,
                    max_orderby=max_orderby,
                    max_expand_paths=max_expand_paths,
                    max_filter_terms=max_filter_terms,
                    nav_path_planner=_plan_nav_path,
                    default_where_provider=default_where_provider,
                )

                # Support $expand=* by materializing wildcards into concrete navs
                if (
                    isinstance(opts.expand, list)
                    and any(ei.path == "*" for ei in opts.expand)
                    and not allow_expand_wildcard
                ):
                    abort(400, "Wildcard expansion not allowed.")

                if isinstance(opts.expand, list) and opts.expand:
                    opts.expand = semantic_checker.materialize_expand_for_url(rgql_url)
                    for item in opts.expand:
                        if "/" in (item.path or ""):
                            abort(
                                400,
                                "Multi-hop $expand paths are not supported; use nested"
                                " $expand=Nav($expand=...)",
                            )
                    opts.expand = [
                        item
                        for item in opts.expand
                        if await ctx.permitted(
                            edm_type=edm_type,
                            path=item.path,
                        )
                    ]

                    expand_paths = {item.path for item in opts.expand}
                    if len(expand_paths) > max_expand_paths:
                        abort(400, f"Max $expand paths ({max_expand_paths}) exceeded.")

            svc_key = resource.service_key
            svc = registry.get_edm_service(svc_key)
            values: list[dict[str, Any]] = []
            count: int | None = None

            delete_filter = default_where_provider(edm_type.name)

            if entity_id is None:
                filter_groups = apply_to_filter_groups(
                    filter_groups,
                    where=delete_filter,
                )

                if filter_groups:
                    fg_sum = 0

                    for fg in filter_groups:
                        fg_sum += len(fg.where)
                        fg_sum += len(fg.scalar_filters)
                        fg_sum += len(fg.text_filters)
                        fg_sum += len(getattr(fg, "related_scalar_filters", []))
                        fg_sum += len(getattr(fg, "related_text_filters", []))

                    if fg_sum > max_filter_terms:
                        abort(
                            400,
                            f"Max filter terms ({max_filter_terms}) exceeded.",
                        )

                try:
                    entities = await svc.list(
                        columns=query_columns,
                        filter_groups=filter_groups,
                        order_by=order_by,
                        limit=limit,
                        offset=offset,
                    )

                    if opts is not None and opts.count:
                        count = await svc.count(filter_groups=filter_groups)
                except SQLAlchemyError as e:
                    current_app.logger.error(e)
                    abort(500)

                if entities is not None:
                    if opts is not None and isinstance(opts.expand, list):
                        for expansion in opts.expand:
                            try:
                                levels_remaining = normalise_expand_levels(
                                    expansion.levels, ctx.max_depth
                                )
                            except ValueError:
                                abort(
                                    400,
                                    f"Unsupported $levels value: {expansion.levels!r}",
                                )

                            try:
                                await expand_navs_bulk(
                                    root_entities=entities,
                                    ctx=ctx,
                                    expand_item=expansion,
                                    current_type_name=edm_type.name,
                                    depth=0,
                                    levels_remaining=levels_remaining,
                                )
                            except RGQLExpandError as e:
                                abort(e.status_code, e.message)

                    for entity in entities:
                        values.append(
                            _serialize_entity(
                                entity=entity,
                                edm_type=edm_type,
                                columns=response_columns,
                                expand_paths=expand_paths,
                            )
                        )
            else:
                try:
                    entity_uuid = uuid.UUID(entity_id)
                except ValueError:
                    abort(400, "Invalid entity ID.")

                where = {"id": entity_uuid}

                where = apply_to_where(where, delete_filter)

                if len(where) > max_filter_terms:
                    abort(
                        400,
                        f"Max filter terms ({max_filter_terms}) exceeded (expand"
                        " recursion).",
                    )

                try:
                    entity = await svc.get(where, columns=query_columns)
                except SQLAlchemyError as e:
                    current_app.logger.error(e)
                    abort(500)

                if entity is None:
                    current_app.logger.debug(f"{edm_type.name} entity not found.")
                    abort(404, "Entity not found.")

                if opts is not None and isinstance(opts.expand, list):
                    for expansion in opts.expand:
                        try:
                            levels_remaining = normalise_expand_levels(
                                expansion.levels, ctx.max_depth
                            )
                        except ValueError:
                            abort(
                                400,
                                f"Unsupported $levels value: {expansion.levels!r}",
                            )

                        try:
                            await expand_navs_bulk(
                                root_entities=[entity],
                                ctx=ctx,
                                expand_item=expansion,
                                current_type_name=edm_type.name,
                                depth=0,
                                levels_remaining=levels_remaining,
                            )
                        except RGQLExpandError as e:
                            abort(e.status_code, e.message)

                values.append(
                    _serialize_entity(
                        entity=entity,
                        edm_type=edm_type,
                        columns=response_columns,
                        expand_paths=expand_paths,
                    )
                )

            kwargs["rgql"] = SimpleNamespace(
                url=rgql_url,
                opts=opts,
                expand=opts.expand if opts is not None else None,
                columns=response_columns,
                filter_groups=filter_groups,
                order_by=order_by,
                limit=limit,
                offset=offset,
                values=values,
                count=count,
            )

            kwargs["edm_type_name"] = edm_type.name
            return await func(*args, **kwargs)

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator

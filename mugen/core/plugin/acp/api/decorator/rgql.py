"""Defines utility decorators for RGQL-enabled API endpoints."""

import uuid
from dataclasses import fields
from functools import wraps
from types import SimpleNamespace
from typing import Any, Sequence

from quart import abort, current_app, request
from sqlalchemy.exc import SQLAlchemyError

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup, OrderBy
from mugen.core.plugin.acp.contract.service.authorization import IAuthorizationService
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.utility.ns import AdminNs
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
from mugen.core.utility.rgql_helper.error import RGQLExpandError
from mugen.core.utility.rgql_helper.rgql_expand import (
    apply_to_filter_groups,
    apply_to_where,
    ExpansionContext,
    expand_navs_bulk,
    normalise_expand_levels,
)
from mugen.core.utility.rgql_helper.rgql_to_relational import (
    RGQLToRelationalAdapter,
)

# pylint: disable=too-many-statements
# pylint: disable=too-many-arguments


def rgql_enabled(
    _fn=None,
    *,
    tenant_kw: str | None = None,
    config_provider=lambda: di.container.config,
    logger_provider=lambda: di.container.logging_gateway,
    auth_provider=lambda: di.container.get_ext_service(di.EXT_SERVICE_ADMIN_SVC_AUTH),
    registry_provider=lambda: di.container.get_ext_service(
        di.EXT_SERVICE_ADMIN_REGISTRY
    ),
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

            allow_global_admin = kwargs.get("allow_global_admin")
            if allow_global_admin is None:
                allow_global_admin = False

            # --- helpers ---
            default_where_provider = make_default_where_provider(
                registry=registry,
                tenant_id=tenant_id,
            )

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
                    title = snake_to_title(f.name)
                    if edm_type.property_redacted(title):
                        continue
                    if columns is None or f.name in columns or title in expand_paths:
                        out[title] = v
                return out

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

                return await auth_svc.has_permission(
                    user_id=auth_user_id,
                    permission_object=perm_obj,
                    permission_type=perm_type,
                    tenant_id=tenant_id,
                    allow_global_admin=allow_global_admin,
                )

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
            order_by: Sequence[OrderBy] | None = None
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

            max_depth = (
                resource.behavior.rgql_max_expand_depth
                if resource.behavior.rgql_max_expand_depth is not None
                else getattr(config.acp, "rgql_max_expand_depth", 3)
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
                    filter_groups, order_by, limit, offset = (
                        adapter.build_relational_query(opts)
                    )

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

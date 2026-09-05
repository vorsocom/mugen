"""Authorize navigation references before RGQL options reach query planning."""

from dataclasses import fields, is_dataclass
from typing import Any, Awaitable, Callable, Sequence

from mugen.core.utility.rgql.apply_parser import GroupByTransform, SearchTransform
from mugen.core.utility.rgql.ast import (
    BinaryOp,
    CastExpr,
    FunctionCall,
    Identifier,
    IsOfExpr,
    LambdaCall,
    Literal,
    MemberAccess,
    UnaryOp,
)
from mugen.core.utility.rgql.model import EdmModel, EdmType

PathPermissionProvider = Callable[[EdmType, str], Awaitable[bool]]
TypeEnvironment = dict[str, EdmType | None]
_SCALAR_FUNCTIONS = frozenset(
    {
        "length",
        "indexof",
        "year",
        "month",
        "day",
        "tolower",
        "toupper",
        "trim",
        "concat",
        "contains",
        "startswith",
        "endswith",
    }
)


async def authorize_query_paths(
    *,
    options: Any,
    edm_type: EdmType,
    model: EdmModel,
    path_permission_provider: PathPermissionProvider,
    search_fields: Sequence[str] = (),
) -> None:
    """Require read permission for every navigation used by query expressions.

    Expansion paths have separate omission and discovery rules; callers authorize
    their tree and invoke this helper for each retained expansion's options.
    Unknown paths remain the semantic checker's or adapter's responsibility.
    Literal payloads and custom transformation strings are never treated as paths.
    """

    async def member(base: EdmType | None, name: str) -> EdmType | None:
        if base is None:
            return None
        nav = base.nav_properties.get(name)
        if nav is not None:
            if not await path_permission_provider(base, name):
                raise PermissionError("Read permission denied for query navigation.")
            return model.try_get_type(nav.target_type.name)
        prop = base.properties.get(name)
        prop_type = getattr(prop, "type", None)
        return model.try_get_type(prop_type.name) if prop_type is not None else None

    async def path(base: EdmType | None, value: str) -> EdmType | None:
        current = base
        for segment in [part.strip() for part in value.split("/") if part.strip()]:
            current = await member(current, segment)
        return current

    async def search(base: EdmType | None) -> None:
        for value in search_fields:
            await path(base, value)

    # pylint: disable=too-many-return-statements
    # pylint: disable=too-many-branches
    async def visit(
        node: Any,
        base: EdmType | None,
        env: TypeEnvironment,
    ) -> EdmType | None:
        if isinstance(node, Literal):
            return None
        if isinstance(node, Identifier):
            if node.name in env:
                return env[node.name]
            return await path(base, node.name)
        if isinstance(node, MemberAccess):
            return await member(await visit(node.base, base, env), node.member)
        if isinstance(node, LambdaCall):
            source = await visit(node.source, base, env)
            nested_env = dict(env)
            if node.var:
                nested_env[node.var] = source
            await visit(node.predicate, source, nested_env)
            return None
        if isinstance(node, (CastExpr, IsOfExpr)):
            await visit(node.source, base, env)
            if isinstance(node, CastExpr):
                return model.try_get_type(node.type_ref.full_name)
            return None
        if isinstance(node, UnaryOp):
            return await visit(node.operand, base, env)
        if isinstance(node, BinaryOp):
            left = await visit(node.left, base, env)
            await visit(node.right, base, env)
            return left
        if isinstance(node, FunctionCall):
            result = None
            for index, argument in enumerate(node.args):
                argument_type = await visit(argument, base, env)
                if index == 0:
                    result = argument_type
            return None if node.name.lower() in _SCALAR_FUNCTIONS else result
        if isinstance(node, GroupByTransform):
            for value in node.grouping_paths:
                await path(base, value)
            await visit(node.sub_transforms, base, env)
            return None
        if isinstance(node, SearchTransform):
            await search(base)
            return None
        if isinstance(node, (list, tuple)):
            for child in node:
                await visit(child, base, env)
        elif is_dataclass(node):
            for field in fields(node):
                await visit(getattr(node, field.name), base, env)
        return None

    environment: TypeEnvironment = {}
    for name, expression in (getattr(options, "param_aliases", None) or {}).items():
        environment[name] = await visit(expression, edm_type, environment)

    await visit(getattr(options, "filter", None), edm_type, environment)
    for item in getattr(options, "orderby", None) or ():
        await visit(getattr(item, "expr", None), edm_type, environment)
    for value in getattr(options, "select", None) or ():
        await path(edm_type, value)
    await visit(getattr(options, "apply", None), edm_type, environment)
    for item in getattr(options, "compute", None) or ():
        await visit(getattr(item, "expr", None), edm_type, environment)
    if getattr(options, "search", None) is not None:
        await search(edm_type)

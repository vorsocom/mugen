"""
Public API for the rgql_parser package.
"""

__all__ = [
    # Expressions
    "Expr",
    "Literal",
    "Identifier",
    "MemberAccess",
    "BinaryOp",
    "UnaryOp",
    "FunctionCall",
    "LambdaCall",
    "TypeRef",
    "CastExpr",
    "IsOfExpr",
    "EnumLiteral",
    "SpatialLiteral",
    "is_boolean_expr",
    "parse_rgql_expr",
    "ParseError",
    # $search
    "SearchExpr",
    "parse_rgql_search",
    # $orderby
    "OrderByItem",
    "parse_orderby",
    # URL + query options
    "RGQLUrl",
    "RGQLPathSegment",
    "RGQLQueryOptions",
    "ExpandItem",
    "parse_rgql_url",
    "parse_expand",
    # $apply
    "ApplyNode",
    "AggregateTransform",
    "AggregateExpression",
    "GroupByTransform",
    "BottomTopTransform",
    "FilterTransform",
    "ApplyOrderByTransform",
    "ApplySearchTransform",
    "ApplySkipTransform",
    "ApplyTopTransform",
    "IdentityTransform",
    "ComputeTransform",
    "ComputeExpression",
    "ConcatTransform",
    "CustomApplyTransform",
    "parse_apply",
    # EDM model
    "EdmModel",
    "EdmType",
    "ModelTypeRef",
    "EdmProperty",
    "EdmNavigationProperty",
    "EntitySet",
    # Semantics
    "SemanticChecker",
    "SemanticError",
    # Normalization
    "simplify_boolean",
    "to_nnf",
    "to_dnf_clauses",
    "dnf_clauses_to_ast",
]

# Expressions
from mugen.core.utility.rgql.ast import (
    Expr,
    Literal,
    Identifier,
    MemberAccess,
    BinaryOp,
    UnaryOp,
    FunctionCall,
    LambdaCall,
    TypeRef,
    CastExpr,
    IsOfExpr,
    EnumLiteral,
    SpatialLiteral,
    is_boolean_expr,
)
from mugen.core.utility.rgql.expr_parser import parse_rgql_expr, ParseError

# $search
from mugen.core.utility.rgql.search_parser import (
    SearchExpr,
    parse_rgql_search,
)

# $orderby
from mugen.core.utility.rgql.orderby_parser import OrderByItem, parse_orderby

# URL + query options
from mugen.core.utility.rgql.url_parser import (
    RGQLUrl,
    RGQLPathSegment,
    RGQLQueryOptions,
    ExpandItem,
    parse_rgql_url,
    parse_expand,
)

# $apply
from mugen.core.utility.rgql.apply_parser import (
    ApplyNode,
    AggregateTransform,
    AggregateExpression,
    GroupByTransform,
    BottomTopTransform,
    FilterTransform,
    OrderByTransform as ApplyOrderByTransform,
    SearchTransform as ApplySearchTransform,
    SkipTransform as ApplySkipTransform,
    TopTransform as ApplyTopTransform,
    IdentityTransform,
    ComputeTransform,
    ComputeExpression,
    ConcatTransform,
    CustomApplyTransform,
    parse_apply,
)

# EDM model + semantics
from mugen.core.utility.rgql.model import (
    EdmModel,
    EdmType,
    TypeRef as ModelTypeRef,
    EdmProperty,
    EdmNavigationProperty,
    EntitySet,
)
from mugen.core.utility.rgql.semantic import SemanticChecker, SemanticError

# Normalization
from mugen.core.utility.rgql.boolean_normalizer import (
    simplify_boolean,
    to_nnf,
    to_dnf_clauses,
    dnf_clauses_to_ast,
)

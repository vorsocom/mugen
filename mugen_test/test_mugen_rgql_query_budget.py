"""Regression checks for bounded RGQL construction and normalization."""

import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import tracemalloc
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from mugen_test.test_mugen_acp_decorator_rgql import rgql_mod
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup
from mugen.core.gateway.storage.rdbms.rgql_adapter.rgql_to_relational import (
    RGQLToRelationalAdapter,
)
from mugen.core.utility.rgql.ast import BinaryOp, FunctionCall, Identifier, UnaryOp
from mugen.core.utility.rgql.boolean_normalizer import to_dnf_clauses
from mugen.core.utility.rgql.expr_parser import ParseError, parse_rgql_expr
from mugen.core.utility.rgql.lexer import RGQLLexer
from mugen.core.utility.rgql.query_budget import (
    MAX_AST_DEPTH,
    MAX_QUERY_LENGTH,
    MAX_QUERY_NODES,
    ParseBudget,
    QueryBudgetError,
)
from mugen.core.utility.rgql.search_parser import parse_rgql_search
from mugen.core.utility.rgql.url_parser import RGQLQueryOptions, parse_rgql_url


def _alternatives(pairs: int = 12) -> str:
    return " and ".join(f"(F{i} eq 1 or F{i} eq 2)" for i in range(pairs))


def _reject_normalization(expression: str, *, expand: bool = False) -> None:
    option = (
        ("$expand", f"Children($filter={expression})")
        if expand
        else ("$filter", expression)
    )
    options = parse_rgql_url("/Things?" + urlencode([option])).query
    if expand:
        options = RGQLQueryOptions(filter=options.expand[0].filter)
    RGQLToRelationalAdapter().build_relational_query(options, max_filter_terms=25)


def _reject_search() -> None:
    expression = " and ".join(f"(a{i} or b{i})" for i in range(12))
    rgql_mod._search_filter_groups(
        parse_rgql_search(expression),
        search_fields=("Name",),
        edm_type=type("Type", (), {"properties": {"Name": object()}})(),
        path_planner=lambda _: None,
        max_filter_terms=25,
    )


def _probe_rejections() -> dict:
    """Exercise safe-sized reproductions inside hard OS process limits."""
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
    expression = _alternatives()
    cases = {
        "filter": lambda: _reject_normalization(expression),
        "expand_filter": lambda: _reject_normalization(expression, expand=True),
        "search": _reject_search,
        "nested_filter": lambda: parse_rgql_expr("(" * 100 + "true" + ")" * 100),
        "nested_search": lambda: parse_rgql_search("(" * 100 + "word" + ")" * 100),
        "nested_apply": lambda: parse_rgql_url(
            "/Things?"
            + urlencode({"$apply": "concat(" * 100 + "identity()" + ")" * 100})
        ),
    }
    results = {}
    for name, operation in cases.items():
        tracemalloc.start()
        started = time.perf_counter()
        try:
            operation()
        except (QueryBudgetError, ParseError) as exc:
            if "Max query" not in str(exc) and "Max filter terms" not in str(exc):
                raise
        else:
            raise AssertionError(f"{name} was not rejected")
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        if elapsed >= 1.0 or peak >= 1024**2:
            raise AssertionError(f"{name}: {elapsed=}, {peak=}")
        results[name] = {"seconds": elapsed, "peak_bytes": peak}
    return results


class TestMugenRgqlQueryBudget(unittest.TestCase):
    """Check rejection before amplified structures are allocated."""

    def test_rejections_have_explicit_time_and_memory_limits(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json; from mugen_test.test_mugen_rgql_query_budget "
                "import _probe_rejections; print(json.dumps(_probe_rejections()))",
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        results = json.loads(result.stdout)
        self.assertEqual(len(results), 6)
        for metrics in results.values():
            self.assertLess(metrics["seconds"], 1.0)
            self.assertLess(metrics["peak_bytes"], 1024**2)

    def test_all_parser_entry_points_share_construction_limits(self) -> None:
        cases = [
            ("$filter", "not " * 100 + "true"),
            ("$filter", "-" * 100 + "1 eq 0"),
            ("$filter", "f(" * 100 + "1" + ")" * 100),
            ("$filter", "cast(1," + "Collection(" * 100 + "Edm.Int32" + ")" * 101),
            ("$filter", "a/any(x:" * 100 + "true" + ")" * 100),
            ("$filter", " and ".join("A eq 1" for _ in range(100))),
            ("$filter", "A in (" + ",".join("1" for _ in range(600)) + ")"),
            ("$filter", "A eq " + "[" * 100 + "1" + "]" * 100),
            ("$search", "not " * 100 + "word"),
            ("$search", " ".join("word" for _ in range(100))),
            ("$expand", "A($expand=" * 100 + "A" + ")" * 100),
            ("$expand", ",".join("A" for _ in range(600))),
            ("$apply", "groupby((A)," * 100 + "identity()" + ")" * 100),
            ("$apply", "/".join("identity()" for _ in range(600))),
            ("$orderby", ",".join("A" for _ in range(600))),
            ("$compute", ",".join(f"1 as A{i}" for i in range(600))),
        ]
        for option, value in cases:
            with self.subTest(option=option, prefix=value[:32]):
                with self.assertRaisesRegex(
                    (QueryBudgetError, ParseError), "Max query"
                ):
                    parse_rgql_url("/Things?" + urlencode({option: value}))
        aliases = [(f"@p{i}", "1") for i in range(600)]
        with self.assertRaisesRegex((QueryBudgetError, ParseError), "nodes"):
            parse_rgql_url("/Things?" + urlencode(aliases))
        # Rejected scopes must release their budget for subsequent requests.
        self.assertIsNotNone(parse_rgql_url("/Things?$filter=A%20eq%201").query.filter)

    def test_length_and_lexer_token_limits_precede_allocation(self) -> None:
        for operation in (
            lambda: parse_rgql_url("x" * (MAX_QUERY_LENGTH + 1)),
            lambda: RGQLLexer("x" * (MAX_QUERY_LENGTH + 1)),
            lambda: RGQLLexer("1 " * (MAX_QUERY_NODES * 4)).tokenize(),
        ):
            with self.assertRaisesRegex(QueryBudgetError, "Max query"):
                operation()

    def test_node_reservation_precedes_constructor(self) -> None:
        budget = ParseBudget()
        factory = Mock(side_effect=lambda: object())
        for _ in range(MAX_QUERY_NODES):
            budget.node(factory)
        with self.assertRaisesRegex(QueryBudgetError, "nodes"):
            budget.node(factory)
        self.assertEqual(factory.call_count, MAX_QUERY_NODES)
        budget = ParseBudget()
        node = budget.node(Identifier, "A")
        for _ in range(MAX_AST_DEPTH - 1):
            node = budget.node(UnaryOp, "not", node)
        with self.assertRaisesRegex(QueryBudgetError, "expression depth"):
            budget.node(UnaryOp, "not", node)

    def test_dnf_limits_include_repeated_terms_and_preserve_boundary(self) -> None:
        expr = parse_rgql_expr(_alternatives(2))
        self.assertEqual(
            [len(group) for group in to_dnf_clauses(expr, max_terms=8)], [2] * 4
        )
        with self.assertRaisesRegex(QueryBudgetError, "Max filter terms"):
            to_dnf_clauses(expr, max_terms=7)
        with self.assertRaisesRegex(QueryBudgetError, "Max filter terms"):
            to_dnf_clauses(parse_rgql_expr("A or B or C"), max_terms=2)
        with self.assertRaisesRegex(QueryBudgetError, "Max filter terms"):
            to_dnf_clauses(Identifier("A"), max_terms=0)
        for expand in (False, True):
            with self.assertRaisesRegex(QueryBudgetError, "Max filter terms"):
                _reject_normalization(_alternatives(), expand=expand)
        with self.assertRaisesRegex(QueryBudgetError, "Max filter terms"):
            _reject_search()

    def test_direct_ast_cannot_bypass_normalization_tree_limits(self) -> None:
        deep = Identifier("A")
        for _ in range(MAX_AST_DEPTH):
            deep = BinaryOp("and", deep, Identifier("B"))
        wide = FunctionCall("f", [Identifier("A") for _ in range(MAX_QUERY_NODES)])
        for expr in (deep, wide):
            with self.assertRaisesRegex(QueryBudgetError, "tree budget"):
                to_dnf_clauses(expr)

    def test_filter_search_product_rejects_before_merging(self) -> None:
        groups = [FilterGroup(where={"a": 1}) for _ in range(3)]
        for left, right in ((groups, None), (None, groups)):
            with self.assertRaisesRegex(QueryBudgetError, "Max filter terms"):
                rgql_mod._and_filter_groups(left, right, max_filter_terms=2)
        with patch.object(rgql_mod, "_merge_filter_groups") as merge:
            with self.assertRaisesRegex(QueryBudgetError, "Max filter terms"):
                rgql_mod._and_filter_groups(groups, groups, max_filter_terms=6)
            merge.assert_not_called()
        self.assertEqual(
            len(rgql_mod._and_filter_groups(groups, groups, max_filter_terms=18)), 9
        )
        with self.assertRaisesRegex(QueryBudgetError, "Max filter terms"):
            rgql_mod._search_filter_groups(
                parse_rgql_search("a or b or c"),
                search_fields=("Name",),
                edm_type=type("Type", (), {"properties": {"Name": object()}})(),
                path_planner=lambda _: None,
                max_filter_terms=2,
            )

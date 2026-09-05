"""Construction limits shared by RGQL parsers and query normalization."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable, Iterator

MAX_QUERY_LENGTH = 32_768
MAX_QUERY_NODES = 512
MAX_QUERY_DEPTH = 32
MAX_AST_DEPTH = 64
DEFAULT_MAX_TERMS = 1_024


class QueryBudgetError(ValueError):
    """Raised before constructing a query that exceeds its resource budget."""


class ParseBudget:
    """Count constructed nodes and recursive descent across a complete URL."""

    def __init__(self) -> None:
        self.depth = 0
        self.nodes: dict[int, tuple[Any, int]] = {}

    @contextmanager
    def descend(self) -> Iterator[None]:
        """Reject recursion before entering another parser frame."""
        if self.depth >= MAX_QUERY_DEPTH:
            raise QueryBudgetError("Max query parser depth exceeded.")
        self.depth += 1
        try:
            yield
        finally:
            self.depth -= 1

    def node(self, factory: Callable, *args: Any, **kwargs: Any) -> Any:
        """Reserve a node and validate tree depth before allocating it."""
        if len(self.nodes) >= MAX_QUERY_NODES:
            raise QueryBudgetError("Max query parser nodes exceeded.")
        depth = 1
        for value in (*args, *kwargs.values()):
            children = value if isinstance(value, (list, tuple)) else (value,)
            for child in children:
                prior = self.nodes.get(id(child))
                if prior is not None:
                    depth = max(depth, prior[1] + 1)
        if depth > MAX_AST_DEPTH:
            raise QueryBudgetError("Max query expression depth exceeded.")
        node = factory(*args, **kwargs)
        self.nodes[id(node)] = (node, depth)
        return node


_ACTIVE_BUDGET: ContextVar[ParseBudget | None] = ContextVar(
    "rgql_parse_budget", default=None
)


def current_parse_budget() -> ParseBudget:
    """Reuse the URL budget, or create a budget for a standalone parser."""
    return _ACTIVE_BUDGET.get() or ParseBudget()


def parser_scope(function: Callable) -> Callable:
    """Share one construction budget through nested query option parsers."""

    @wraps(function)
    def bounded(text: str, *args: Any, **kwargs: Any) -> Any:
        if len(text) > MAX_QUERY_LENGTH:
            raise QueryBudgetError("Max query length exceeded.")
        budget = current_parse_budget()
        token = _ACTIVE_BUDGET.set(budget)
        try:
            with budget.descend():
                return function(text, *args, **kwargs)
        finally:
            _ACTIVE_BUDGET.reset(token)

    return bounded


def parser_depth(function: Callable) -> Callable:
    """Guard recursive grammar edges before invoking the parser method."""

    @wraps(function)
    def bounded(parser: Any, *args: Any, **kwargs: Any) -> Any:
        with parser.budget.descend():
            return function(parser, *args, **kwargs)

    return bounded


def check_normalization_budget(groups: int, terms: int, max_terms: int) -> None:
    """Check a prospective DNF size before concatenation or multiplication."""
    if groups > max_terms or terms > max_terms:
        raise QueryBudgetError(f"Max filter terms ({max_terms}) exceeded.")

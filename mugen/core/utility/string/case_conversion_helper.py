"""Provides helper functions for snake_case <--> TitleCase coversions."""

__all__ = [
    "snake_to_title",
    "title_to_snake",
    "snake_keys_to_title",
    "title_keys_to_snake",
]

import re
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# String converters
# ---------------------------------------------------------------------------


def snake_to_title(name: str) -> str:
    """Convert 'snake_case' to 'TitleCase' (PascalCase-like).

    Examples
    --------
    >>> snake_to_title("user_id")
    'UserId'
    >>> snake_to_title("is_active")
    'IsActive'
    >>> snake_to_title("id")
    'Id'
    """
    if not name:
        return name

    parts = name.split("_")
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


# Precompiled regexes for title_to_snake
# e.g. "UserId" -> "user_id"
_TITLE_TO_SNAKE_1 = re.compile(r"(.)([A-Z][a-z0-9]+)")
_TITLE_TO_SNAKE_2 = re.compile(r"([a-z0-9])([A-Z])")


def title_to_snake(name: str) -> str:
    """Convert 'TitleCase' / 'PascalCase' to 'snake_case'.

    Examples
    --------
    >>> title_to_snake("UserId")
    'user_id'
    >>> title_to_snake("IsActive")
    'is_active'
    >>> title_to_snake("Id")
    'id'
    """
    if not name:
        return name

    # Insert underscores at word boundaries, then lowercase
    s1 = _TITLE_TO_SNAKE_1.sub(r"\1_\2", name)
    s2 = _TITLE_TO_SNAKE_2.sub(r"\1_\2", s1)
    return s2.lower()


# ---------------------------------------------------------------------------
# Recursive key converters
# ---------------------------------------------------------------------------


def snake_keys_to_title(obj: Any) -> Any:
    """Recursively convert dict keys from snake_case to TitleCase.

    Works on:
      * dicts (converts keys)
      * lists/tuples of dicts (recurse into elements)
      * everything else is returned as-is

    Examples
    --------
    >>> snake_keys_to_title({"user_id": 1, "is_active": True})
    {'UserId': 1, 'IsActive': True}
    """
    if isinstance(obj, Mapping):
        return {snake_to_title(str(k)): snake_keys_to_title(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(snake_keys_to_title(v) for v in obj)
    return obj


def title_keys_to_snake(obj: Any) -> Any:
    """Recursively convert dict keys from TitleCase to snake_case.

    Works on:
      * dicts (converts keys)
      * lists/tuples of dicts (recurse into elements)
      * everything else is returned as-is

    Examples
    --------
    >>> title_keys_to_snake({"UserId": 1, "IsActive": True})
    {'user_id': 1, 'is_active': True}
    """
    if isinstance(obj, Mapping):
        return {title_to_snake(str(k)): title_keys_to_snake(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(title_keys_to_snake(v) for v in obj)
    return obj

"""
namespace.py

Utilities for converting nested Python mappings into ``types.SimpleNamespace`` objects.

Primary use-case
----------------
You have configuration-like data (often deserialized from JSON/YAML) and want a structure
supporting a *mix* of:

- Dot access for identifier-like keys: ``ns.user.name``
- ``getattr`` for arbitrary keys: ``getattr(ns, "foo-bar")``

This module provides:

- ``to_namespace``: a pure function that recursively converts an object graph.
- ``nested_namespace_from_dict``: a backwards-compatible wrapper that mutates an
  existing ``SimpleNamespace`` in place by calling ``to_namespace`` and merging.

Design notes
------------
- Mapping keys are preserved verbatim as attributes (stringified if necessary).
  This guarantees ``getattr(ns, key)`` works for string keys.
- For keys that are not valid Python identifiers, an optional alias can be generated
  (e.g., ``"foo-bar" -> "foo_bar"``) so you can still use dot access when desired.
- Raw mappings and alias maps may be attached to each created namespace node to aid
  debugging and introspection. These are stored under reserved attributes by default.

Alias collision policy
----------------------
When alias generation is enabled, two different keys may sanitize to the same alias,
or the alias may collide with an existing attribute (including a real user key).
You can control this deterministically via ``NamespaceConfig.alias_collision_policy``:

- ``"skip"``   : do not create an alias if it would collide.
- ``"suffix"`` : create a unique alias by appending a numeric suffix (default).
- ``"error"``  : raise ``ValueError`` on the first collision.

Example
-------
>>> data = {"user": {"full-name": "Ada"}, "items": [{"id": 1}, {"id": 2}]}
>>> ns = to_namespace(data)
>>> ns.user.full_name
'Ada'
>>> getattr(ns.user, "full-name")
'Ada'
>>> ns.items[0].id
1
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import keyword
import re
from types import SimpleNamespace
from typing import Any, Literal

__all__ = ["NamespaceConfig", "to_namespace", "nested_namespace_from_dict"]


def _is_dot_accessible(name: str) -> bool:
    """Return True if ``name`` is a valid non-keyword Python identifier."""
    return name.isidentifier() and not keyword.iskeyword(name)


def _sanitize_key(name: str) -> str:
    """
    Create a best-effort identifier-like alias for dot access.

    Rules:
    - Replace non-identifier characters with underscores.
    - Prefix underscore if the result starts with a digit.
    - Suffix underscore if the result is a Python keyword.

    Note: Alias collision handling is governed by ``NamespaceConfig``.
    """
    alias = re.sub(r"\W", "_", name)
    if not alias:
        alias = "_"
    if alias[0].isdigit():
        alias = "_" + alias
    if keyword.iskeyword(alias):
        alias = alias + "_"
    return alias


def _choose_internal_attr(source: Mapping[Any, Any], desired: str) -> str:
    """
    Pick an internal attribute name that won't clobber a user key.

    If the desired name exists as a key in the source mapping, we fall back to
    appending ``"__"``.
    """
    source_keys = {k if isinstance(k, str) else str(k) for k in source.keys()}
    return desired if desired not in source_keys else f"{desired}__"


def _unique_alias(
    ns: SimpleNamespace,
    base: str,
    *,
    used_aliases: Mapping[str, str],
    policy: Literal["skip", "suffix", "error"],
    sep: str,
    start_index: int,
) -> str | None:
    """
    Choose an alias name according to the configured collision policy.

    Returns:
      - A unique alias string to use, or
      - None if policy=="skip" and base collides.

    Collisions are checked against:
      - existing attributes on the namespace (including user keys),
      - already-created aliases for this node.
    """

    def collides(candidate: str) -> bool:
        return hasattr(ns, candidate) or candidate in used_aliases

    if not collides(base):
        return base

    if policy == "skip":
        return None

    if policy == "error":
        raise ValueError(f"Alias collision: '{base}' already exists on namespace")

    # policy == "suffix"
    i = max(2, int(start_index))
    while True:
        candidate = f"{base}{sep}{i}"
        if not collides(candidate):
            return candidate
        i += 1


@dataclass(frozen=True, slots=True)
class NamespaceConfig:
    """
    Configuration for namespace conversion.

    Attributes
    ----------
    keep_raw:
        If True, attach a shallow copy of the source mapping to each created namespace.
    raw_attr:
        Attribute name to store raw mapping copies. If the source mapping already has
        this key, a non-conflicting fallback name is used (``raw_attr + "__"``).
    add_aliases:
        If True, generate dot-friendly aliases for non-identifier keys.
    aliases_attr:
        Attribute name to store a mapping of ``alias -> original_key``. If the source
        mapping already has this key, a non-conflicting fallback name is used
        (``aliases_attr + "__"``).
    alias_collision_policy:
        How to handle alias collisions:
          - "skip": do not create a colliding alias.
          - "suffix": append numeric suffix until unique (deterministic).
          - "error": raise ValueError on collision.
    alias_suffix_separator:
        Separator used when ``alias_collision_policy="suffix"`` (default "__").
    alias_suffix_start:
        Starting integer suffix (default 2), producing e.g. ``name__2``.
    """

    keep_raw: bool = True
    raw_attr: str = "_raw"
    add_aliases: bool = True
    aliases_attr: str = "_aliases"

    alias_collision_policy: Literal["skip", "suffix", "error"] = "suffix"
    alias_suffix_separator: str = "__"
    alias_suffix_start: int = 2


_DEFAULT_CONFIG = NamespaceConfig()


def to_namespace(obj: Any, cfg: NamespaceConfig = _DEFAULT_CONFIG) -> Any:
    """
    Recursively convert an object graph into ``SimpleNamespace`` objects.

    Conversion rules
    ----------------
    - ``Mapping`` -> ``SimpleNamespace`` (values recursively converted)
    - ``list``/``tuple`` -> ``list`` (elements recursively converted)
    - scalars -> unchanged

    Access semantics
    ---------------
    - Original keys are preserved as attributes (stringified if needed). This ensures
      ``getattr(ns, key)`` works for arbitrary key strings.
    - If ``cfg.add_aliases`` is enabled, alias attributes are created for keys that
      are not dot-accessible identifiers, controlled by
      ``cfg.alias_collision_policy``. Aliases never overwrite existing attributes.
    """
    if obj is None:
        return None

    if isinstance(obj, SimpleNamespace):
        return obj

    if isinstance(obj, Mapping):
        ns = SimpleNamespace()

        raw_attr = _choose_internal_attr(obj, cfg.raw_attr)
        aliases_attr = _choose_internal_attr(obj, cfg.aliases_attr)

        if cfg.keep_raw and not hasattr(ns, raw_attr):
            setattr(ns, raw_attr, dict(obj))

        aliases: dict[str, str] = {}

        # First pass: set original keys as attributes (so collisions are measured
        # against real keys, not just previously processed ones).
        converted_items: list[tuple[str, Any]] = []
        for k, v in obj.items():
            key = k if isinstance(k, str) else str(k)
            converted_items.append((key, to_namespace(v, cfg)))

        for key, converted in converted_items:
            setattr(ns, key, converted)

        # Second pass: create aliases if configured.
        if cfg.add_aliases:
            for key, converted in converted_items:
                if _is_dot_accessible(key):
                    continue

                base = _sanitize_key(key)
                alias = _unique_alias(
                    ns,
                    base,
                    used_aliases=aliases,
                    policy=cfg.alias_collision_policy,
                    sep=cfg.alias_suffix_separator,
                    start_index=cfg.alias_suffix_start,
                )
                if alias is None:
                    continue

                # Create alias attribute and record reverse map.
                setattr(ns, alias, converted)
                aliases[alias] = key

        if cfg.add_aliases and aliases and not hasattr(ns, aliases_attr):
            setattr(ns, aliases_attr, aliases)

        return ns

    # Treat sequences as lists, but avoid iterating strings/bytes.
    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        return [to_namespace(v, cfg) for v in obj]

    return obj


def nested_namespace_from_dict(items: Any, ns: SimpleNamespace) -> None:
    """
    Mutate ``ns`` in-place by converting ``items`` via ``to_namespace`` and merging.

    This is a backwards-compatible API for codebases that pass an existing namespace
    instance to be populated.

    Parameters
    ----------
    items:
        A mapping (typically ``dict``) to convert. If ``None`` or not a mapping, the
        function is a no-op (matching historical behavior).
    ns:
        The namespace instance to populate (mutated in place).
    """
    if items is None or not isinstance(items, Mapping):
        return

    converted = to_namespace(items)
    if isinstance(converted, SimpleNamespace):
        ns.__dict__.update(converted.__dict__)

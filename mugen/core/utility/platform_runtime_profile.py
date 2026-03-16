"""Helpers for runtime config namespace conversion."""

from __future__ import annotations

__all__ = ["build_config_namespace"]

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from mugen.core.utility.collection.namespace import NamespaceConfig, to_namespace

_CONFIG_NAMESPACE_CONVERSION = NamespaceConfig(
    keep_raw=True,
    raw_attr="dict",
    add_aliases=False,
)


def build_config_namespace(config: Mapping[str, Any]) -> SimpleNamespace:
    """Convert one config mapping into the repo's runtime namespace shape."""
    if not isinstance(config, Mapping):
        raise TypeError("Configuration root must be a mapping.")

    converted = to_namespace(dict(config), cfg=_CONFIG_NAMESPACE_CONVERSION)
    if not isinstance(converted, SimpleNamespace):
        raise TypeError("Configuration namespace conversion failed.")
    return converted

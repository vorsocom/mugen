"""
Resolve ACP identity from the unified framework extension configuration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

ACP_FRAMEWORK_TOKEN = "core.fw.acp"


@dataclass(frozen=True, slots=True)
class AcpIdentity:
    """
    Canonical ACP identity derived from the framework extension contract.
    """

    token: str
    namespace: str
    name: str | None = None
    contrib: str | None = None


def resolve_acp_identity(
    config: Any,
    *,
    enabled_only: bool = False,
) -> AcpIdentity:
    """
    Resolve ACP identity from ``mugen.modules.extensions``.
    """
    entries = _configured_extensions(config)
    matches: list[AcpIdentity] = []

    for index, entry in enumerate(entries):
        resolved = _resolve_identity_entry(
            entry,
            index=index,
            enabled_only=enabled_only,
        )
        if resolved is not None:
            matches.append(resolved)

    if not matches:
        qualifier = "enabled " if enabled_only else ""
        raise RuntimeError(
            "Invalid ACP configuration: "
            f"{qualifier}framework extension token {ACP_FRAMEWORK_TOKEN!r} "
            "is required in mugen.modules.extensions."
        )

    identity = matches[0]
    for candidate in matches[1:]:
        if candidate != identity:
            raise RuntimeError(
                "Invalid ACP configuration: conflicting mugen.modules.extensions "
                f"entries found for token {ACP_FRAMEWORK_TOKEN!r}."
            )
    return identity


def resolve_acp_admin_namespace(
    config: Any,
    *,
    enabled_only: bool = False,
) -> str:
    """
    Return the canonical ACP admin namespace.
    """
    return resolve_acp_identity(config, enabled_only=enabled_only).namespace


def _configured_extensions(config: Any) -> list[Any]:
    mugen_cfg = _field(config, "mugen", None)
    modules_cfg = _field(mugen_cfg, "modules", None)
    extensions = _field(modules_cfg, "extensions", [])

    if extensions is None:
        return []
    if not isinstance(extensions, list):
        raise RuntimeError(
            "Invalid ACP configuration: mugen.modules.extensions must be a list."
        )
    return list(extensions)


def _resolve_identity_entry(
    entry: Any,
    *,
    index: int,
    enabled_only: bool,
) -> AcpIdentity | None:
    if not _supports_fields(entry):
        raise RuntimeError(
            "Invalid ACP configuration: "
            f"mugen.modules.extensions[{index}] must be a table."
        )

    token = _normalized_optional_str(_field(entry, "token", ""), lowercase=True)
    if token != ACP_FRAMEWORK_TOKEN:
        return None

    entry_type = _normalized_optional_str(_field(entry, "type", ""), lowercase=True)
    if entry_type != "fw":
        raise RuntimeError(
            "Invalid ACP configuration: "
            f"mugen.modules.extensions[{index}] for token {ACP_FRAMEWORK_TOKEN!r} "
            "must declare type='fw'."
        )

    if enabled_only and not bool(_field(entry, "enabled", False)):
        return None

    namespace = _normalized_optional_str(_field(entry, "namespace", ""))
    if namespace is None:
        raise RuntimeError(
            "Invalid ACP configuration: "
            f"mugen.modules.extensions[{index}].namespace is required for token "
            f"{ACP_FRAMEWORK_TOKEN!r}."
        )

    return AcpIdentity(
        token=ACP_FRAMEWORK_TOKEN,
        namespace=namespace,
        name=_normalized_optional_str(_field(entry, "name", None)),
        contrib=_normalized_optional_str(_field(entry, "contrib", None)),
    )


def _field(obj: Any, key: str, default: Any) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    if isinstance(obj, SimpleNamespace):
        return getattr(obj, key, default)
    return default


def _normalized_optional_str(value: Any, *, lowercase: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    if normalized == "":
        return None
    if lowercase:
        return normalized.lower()
    return normalized


def _supports_fields(value: Any) -> bool:
    return isinstance(value, (Mapping, SimpleNamespace))

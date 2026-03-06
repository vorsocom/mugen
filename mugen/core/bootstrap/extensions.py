"""Extension bootstrap registry and token resolution helpers."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from types import SimpleNamespace
from typing import Any

from mugen.core.contract.extension.cp import ICPExtension
from mugen.core.contract.extension.ct import ICTExtension
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.extension.registry import IExtensionRegistry
from mugen.core.contract.extension.rpp import IRPPExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.platform import IPlatformService

_KNOWN_EXTENSION_TYPES = {"cp", "ct", "fw", "ipc", "mh", "rpp"}
_PLUGIN_EXTENSION_REGISTRY_MODULE = "mugen.core.plugin.token_registry"
_PLUGIN_EXTENSION_REGISTRY_FUNC = "get_plugin_extension_token_registry"


def parse_bool(value: object, *, default: bool) -> bool:
    """Parse bool-like values with deterministic defaults."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


@dataclass(frozen=True)
class ExtensionTokenSpec:
    """Resolved extension token metadata."""

    extension_type: str
    interface: type
    extension_class: type


@dataclass(frozen=True)
class _ExtensionClassRef:
    extension_type: str
    interface: type
    module_path: str
    class_name: str


_CORE_EXTENSION_TOKEN_REGISTRY: dict[str, _ExtensionClassRef] = {
    "core.cp.clear_history": _ExtensionClassRef(
        "cp",
        ICPExtension,
        "mugen.core.extension.cp.clear_history",
        "ClearChatHistoryICPExtension",
    ),
}

_PLUGIN_EXTENSION_TOKEN_REGISTRY_CACHE: dict[str, _ExtensionClassRef] | None = None


def _normalize_extension_token(token: object) -> str:
    if not isinstance(token, str):
        raise RuntimeError("Invalid extension token: expected a string.")
    normalized = token.strip().lower()
    if normalized == "":
        raise RuntimeError("Invalid extension token: token must be non-empty.")
    if ":" in normalized:
        raise RuntimeError("Invalid extension token: module:Class paths are not supported.")
    return normalized


def _parse_plugin_extension_class_ref(
    token: str,
    raw_ref: object,
) -> _ExtensionClassRef:
    if (
        not isinstance(raw_ref, tuple)
        or len(raw_ref) != 4
        or not isinstance(raw_ref[0], str)
        or not isinstance(raw_ref[1], type)
        or not isinstance(raw_ref[2], str)
        or not isinstance(raw_ref[3], str)
    ):
        raise RuntimeError(
            "Invalid plugin extension class binding "
            f"for token: {token!r}."
        )

    return _ExtensionClassRef(
        extension_type=raw_ref[0],
        interface=raw_ref[1],
        module_path=raw_ref[2],
        class_name=raw_ref[3],
    )


def _plugin_extension_token_registry() -> dict[str, _ExtensionClassRef]:
    global _PLUGIN_EXTENSION_TOKEN_REGISTRY_CACHE
    if _PLUGIN_EXTENSION_TOKEN_REGISTRY_CACHE is not None:
        return _PLUGIN_EXTENSION_TOKEN_REGISTRY_CACHE

    try:
        module = importlib.import_module(_PLUGIN_EXTENSION_REGISTRY_MODULE)
        provider = getattr(module, _PLUGIN_EXTENSION_REGISTRY_FUNC)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise RuntimeError("Invalid plugin extension token registry configuration.") from exc

    if callable(provider) is not True:
        raise RuntimeError("Invalid plugin extension token registry configuration.")

    raw_registry = provider()
    if not isinstance(raw_registry, dict):
        raise RuntimeError("Invalid plugin extension token registry configuration.")

    parsed_registry: dict[str, _ExtensionClassRef] = {}
    for raw_token, raw_ref in raw_registry.items():
        token = _normalize_extension_token(raw_token)
        parsed_registry[token] = _parse_plugin_extension_class_ref(token, raw_ref)

    _PLUGIN_EXTENSION_TOKEN_REGISTRY_CACHE = parsed_registry
    return parsed_registry


def _resolve_extension_spec_from_registry(
    *,
    token: str,
    registry: dict[str, _ExtensionClassRef],
) -> ExtensionTokenSpec:
    class_ref = registry.get(token)
    if class_ref is None:
        known_tokens = ", ".join(sorted(registry.keys()))
        raise RuntimeError(
            f"Unknown extension token: {token!r}. Known tokens: {known_tokens}."
        )

    try:
        module = importlib.import_module(class_ref.module_path)
        extension_class = getattr(module, class_ref.class_name)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise RuntimeError(
            f"Invalid extension class binding for token: {token!r}."
        ) from exc

    if not isinstance(extension_class, type):
        raise RuntimeError(f"Invalid extension class binding for token: {token!r}.")
    if not issubclass(extension_class, class_ref.interface):
        raise RuntimeError(f"Invalid extension class binding for token: {token!r}.")

    return ExtensionTokenSpec(
        extension_type=class_ref.extension_type,
        interface=class_ref.interface,
        extension_class=extension_class,
    )


def resolve_extension_spec(
    token: object,
    *,
    scope: str = "any",
) -> ExtensionTokenSpec:
    """Resolve extension token to explicit class/interface metadata."""
    normalized_token = _normalize_extension_token(token)
    normalized_scope = str(scope or "").strip().lower()

    if normalized_scope == "core":
        registry = _CORE_EXTENSION_TOKEN_REGISTRY
    elif normalized_scope == "plugin":
        registry = _plugin_extension_token_registry()
    elif normalized_scope == "any":
        registry = {
            **_CORE_EXTENSION_TOKEN_REGISTRY,
            **_plugin_extension_token_registry(),
        }
    else:
        raise RuntimeError("Invalid extension token scope.")

    return _resolve_extension_spec_from_registry(
        token=normalized_token,
        registry=registry,
    )


class DefaultExtensionRegistry(IExtensionRegistry):
    """Core extension registration coordinator."""

    def __init__(
        self,
        *,
        messaging_service: IMessagingService,
        ipc_service: IIPCService,
        platform_service: IPlatformService,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._messaging_service = messaging_service
        self._ipc_service = ipc_service
        self._platform_service = platform_service
        self._logging_gateway = logging_gateway

    async def register(
        self,
        *,
        app: Any,
        extension_type: str,
        extension,
        token: str,
        critical: bool,
    ) -> bool:
        ext_type = str(extension_type).strip().lower()
        if ext_type in {"ctx", "rag"}:
            raise RuntimeError(
                "Legacy extension types 'ctx' and 'rag' are unsupported. "
                "Use the context engine service boundary instead."
            )
        if ext_type not in _KNOWN_EXTENSION_TYPES:
            raise RuntimeError(f"Unknown extension type: {extension_type!r}.")
        if self._platform_service.extension_supported(extension) is not True:
            self._logging_gateway.warning(
                f"Extension not supported by active platforms: {token}."
            )
            return False

        if ext_type == "fw":
            await extension.setup(app)
            return True
        if ext_type == "ipc":
            self._bind_ipc_extension(extension=extension, critical=critical)
            return True
        self._bind_messaging_extension(
            extension_type=ext_type,
            extension=extension,
            critical=critical,
        )
        return True

    def _bind_ipc_extension(
        self,
        *,
        extension: IIPCExtension,
        critical: bool,
    ) -> None:
        self._ipc_service.bind_ipc_extension(extension, critical=critical)

    def _bind_messaging_extension(
        self,
        *,
        extension_type: str,
        extension,
        critical: bool,
    ) -> None:
        if extension_type == "cp":
            self._messaging_service.bind_cp_extension(extension, critical=critical)
            return
        if extension_type == "ct":
            self._messaging_service.bind_ct_extension(extension, critical=critical)
            return
        if extension_type == "mh":
            self._messaging_service.bind_mh_extension(extension, critical=critical)
            return
        if extension_type == "rpp":
            self._messaging_service.bind_rpp_extension(extension, critical=critical)
            return
        raise RuntimeError(
            f"Messaging extension binding is unavailable for type {extension_type!r}."
        )


def configured_core_extensions(config: SimpleNamespace) -> list[SimpleNamespace]:
    """Return core-owned extension configuration rows."""
    modules_config = getattr(
        getattr(config, "mugen", SimpleNamespace()),
        "modules",
        SimpleNamespace(),
    )
    core_modules_config = getattr(modules_config, "core", SimpleNamespace())

    core_extensions = getattr(core_modules_config, "extensions", [])
    if core_extensions is None:
        core_extensions = []
    if not isinstance(core_extensions, list):
        raise RuntimeError(
            "Invalid extension configuration: mugen.modules.core.extensions must be a list."
        )
    return list(core_extensions)


def configured_downstream_extensions(config: SimpleNamespace) -> list[SimpleNamespace]:
    """Return plugin/downstream extension configuration rows."""
    modules_config = getattr(
        getattr(config, "mugen", SimpleNamespace()),
        "modules",
        SimpleNamespace(),
    )
    downstream_extensions = getattr(modules_config, "extensions", [])
    if downstream_extensions is None:
        downstream_extensions = []
    if not isinstance(downstream_extensions, list):
        raise RuntimeError(
            "Invalid extension configuration: mugen.modules.extensions must be a list."
        )
    return list(downstream_extensions)


def configured_extensions(config: SimpleNamespace) -> list[SimpleNamespace]:
    """Return merged extension configuration rows."""
    return (
        configured_core_extensions(config)
        + configured_downstream_extensions(config)
    )

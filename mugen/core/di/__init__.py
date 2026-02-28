"""Provides an application-wide dependency injection container."""

__all__ = [
    "EXT_SERVICE_ADMIN_REGISTRY",
    "EXT_SERVICE_ADMIN_SANDBOX_ENFORCER",
    "EXT_SERVICE_ADMIN_SVC_AUTH",
    "EXT_SERVICE_ADMIN_SVC_JWT",
    "build_container",
    "container",
    "reset_container",
    "shutdown_container",
    "shutdown_container_async",
]

import asyncio
from importlib import import_module
import inspect
import logging
import os
from dataclasses import dataclass
from types import SimpleNamespace

import tomlkit

from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.client.web import IWebClient
from mugen.core.contract.client.whatsapp import IWhatsAppClient
from mugen.core.contract.gateway.completion import ICompletionGateway
from mugen.core.contract.gateway.email import IEmailGateway
from mugen.core.contract.gateway.knowledge import IKnowledgeGateway
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.web_runtime import IWebRuntimeStore
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.nlp import INLPService
from mugen.core.contract.service.platform import IPlatformService
from mugen.core.contract.service.user import IUserService
from mugen.core.utility.collection.namespace import NamespaceConfig, to_namespace
from mugen.core.utility.platforms import normalize_platforms, unknown_platforms

from .injector import DependencyInjector

EXT_SERVICE_ADMIN_REGISTRY = "admin_registry"
EXT_SERVICE_ADMIN_SANDBOX_ENFORCER = "admin_sandbox_enforcer"
EXT_SERVICE_ADMIN_SVC_JWT = "admin_svc_jwt"
EXT_SERVICE_ADMIN_SVC_AUTH = "admin_svc_auth"

_CONFIG_NAMESPACE_CONVERSION = NamespaceConfig(
    keep_raw=True,
    raw_attr="dict",
    add_aliases=False,
)


class ContainerBootstrapError(RuntimeError):
    """Raised when DI container bootstrap configuration is invalid."""


class ProviderBootstrapError(ContainerBootstrapError):
    """Raised when a required provider fails deterministic bootstrap."""


def _nested_namespace_from_dict(items: dict, ns: SimpleNamespace) -> None:
    """Convert a nested dict to a nested SimpleNamespace."""
    if not isinstance(items, dict):
        raise TypeError("Configuration root must be a dict.")
    if not isinstance(ns, SimpleNamespace):
        raise TypeError("Target namespace must be SimpleNamespace.")
    converted = to_namespace(items, cfg=_CONFIG_NAMESPACE_CONVERSION)
    if isinstance(converted, SimpleNamespace):
        ns.__dict__.update(converted.__dict__)


def _build_config_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """Build configuration provider object for DI container."""
    if not isinstance(config, dict):
        raise RuntimeError("Configuration payload must be a dict.")

    ns = SimpleNamespace()
    _nested_namespace_from_dict(config, ns)
    if not isinstance(injector, DependencyInjector):
        raise RuntimeError("Invalid dependency injector instance.")
    injector.config = ns


def _split_class_path(
    raw_value: object,
    *,
    provider_name: str,
) -> tuple[str, str]:
    """Parse mandatory module:Class provider path."""
    if not isinstance(raw_value, str):
        raise RuntimeError(
            "Invalid configuration "
            f"({provider_name}): expected module:Class string."
        )
    normalized = raw_value.strip()
    if ":" not in normalized:
        raise RuntimeError(
            "Invalid configuration "
            f"({provider_name}): module-only paths are not supported; use module:Class."
        )
    module_name, class_name = normalized.split(":", 1)
    module_name = module_name.strip()
    class_name = class_name.strip()
    if module_name == "" or class_name == "":
        raise RuntimeError(
            "Invalid configuration "
            f"({provider_name}): expected non-empty module and class in module:Class."
        )
    return module_name, class_name


def _config_path_exists(config: dict, *path: str) -> bool:
    """Check whether a nested key path exists in the dict configuration."""
    node: dict | object = config
    for key in path:
        if not isinstance(node, dict):
            return False
        if key not in node:
            return False
        node = node[key]
    return True


def _config_path_value(config: dict, *path: str):
    node = config
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _validate_removed_legacy_paths(
    config: dict,
    logger: ILoggingGateway | logging.Logger,
) -> None:
    keyval_module = _config_path_value(
        config,
        "mugen",
        "modules",
        "core",
        "gateway",
        "storage",
        "keyval",
    )
    if str(keyval_module).strip() == "mugen.core.gateway.storage.keyval.dbm":
        logger.error(
            "Removed legacy keyval backend configured: mugen.core.gateway.storage.keyval.dbm"
        )
        raise RuntimeError(
            "Legacy keyval DBM backend is no longer supported. "
            "Use mugen.core.gateway.storage.keyval.relational."
        )

    if _config_path_exists(
        config,
        "mugen",
        "storage",
        "keyval",
        "legacy_import",
    ):
        logger.error(
            "Removed keyval legacy import configuration detected: mugen.storage.keyval.legacy_import"
        )
        raise RuntimeError(
            "Legacy keyval startup import is no longer supported. "
            "Remove mugen.storage.keyval.legacy_import from configuration."
        )

    if _config_path_exists(config, "mugen", "modules", "core", "client", "telnet"):
        logger.error("Removed core telnet client configuration detected.")
        raise RuntimeError(
            "Core telnet client is no longer supported. "
            "Use the dev/test telnet harness module instead of core runtime wiring."
        )


def _get_active_platforms(config: dict) -> list[str] | None:
    """Get configured platform list from app configuration."""
    try:
        platforms = config["mugen"]["platforms"]
    except (KeyError, TypeError):
        return None

    if not isinstance(platforms, list):
        return None

    return platforms


def _normalize_platforms(values: list[str] | None) -> list[str]:
    return normalize_platforms(values)


def _resolve_runtime_profile_override(config: dict) -> str:
    runtime_cfg = config.get("mugen", {}).get("runtime")
    if not isinstance(runtime_cfg, dict):
        raise RuntimeError(
            "Invalid runtime profile configuration: "
            "mugen.runtime.profile is required and must be a string."
        )
    if "profile" not in runtime_cfg:
        raise RuntimeError(
            "Invalid runtime profile configuration: "
            "mugen.runtime.profile is required and must be one of "
            "api_only|web_only|platform_full."
        )
    raw_profile = runtime_cfg.get("profile")
    if not isinstance(raw_profile, str):
        raise RuntimeError(
            "Invalid runtime profile configuration: mugen.runtime.profile must be a string."
        )

    normalized = raw_profile.strip().lower()
    if normalized in {"", "auto"}:
        raise RuntimeError(
            "Invalid runtime profile configuration: mugen.runtime.profile must be "
            "explicitly set to one of api_only|web_only|platform_full."
        )

    if normalized not in {"api_only", "web_only", "platform_full"}:
        raise RuntimeError(
            "Invalid runtime profile configuration: "
            "mugen.runtime.profile must be one of api_only|web_only|platform_full."
        )
    return normalized


def _infer_runtime_profile(config: dict) -> str:
    """Resolve explicit DI runtime validation profile."""
    return _resolve_runtime_profile_override(config)


def _validate_container(config: dict, injector: DependencyInjector) -> None:
    """Validate that required providers were built for active configuration."""
    profile = _infer_runtime_profile(config)
    active_platforms = _normalize_platforms(_get_active_platforms(config))
    active_platform_set = set(active_platforms)
    unsupported_platforms = unknown_platforms(active_platforms)

    logger = injector.logging_gateway
    if logger is None:
        logger = logging.getLogger()

    _validate_removed_legacy_paths(config, logger)

    if unsupported_platforms:
        unsupported_platforms_text = ", ".join(unsupported_platforms)
        logger.error(
            "Unsupported platform configuration detected: %s.",
            unsupported_platforms_text,
        )
        raise RuntimeError(
            "Unsupported platform configuration: "
            f"{unsupported_platforms_text}. "
            "Allowed values are matrix, web, whatsapp."
        )

    if profile == "api_only" and active_platforms:
        logger.error(
            "Runtime profile api_only cannot be used when platforms are enabled."
        )
        raise RuntimeError("Runtime profile api_only requires mugen.platforms to be empty.")

    if profile == "web_only" and active_platform_set != {"web"}:
        logger.error(
            "Runtime profile web_only requires mugen.platforms to contain only 'web'."
        )
        raise RuntimeError(
            "Runtime profile web_only requires mugen.platforms=['web']."
        )

    if profile == "platform_full" and not active_platforms:
        logger.error(
            "Runtime profile platform_full requires one or more enabled platforms."
        )
        raise RuntimeError(
            "Runtime profile platform_full requires at least one enabled platform."
        )

    required = [
        "config",
        "logging_gateway",
        "completion_gateway",
        "ipc_service",
        "keyval_storage_gateway",
        "nlp_service",
        "platform_service",
        "user_service",
        "messaging_service",
    ]
    if "web" in active_platform_set:
        required.append("relational_storage_gateway")
        required.append("web_runtime_store")

    missing = [name for name in required if getattr(injector, name) is None]

    if _config_path_exists(config, "mugen", "modules", "core", "gateway", "knowledge"):
        if injector.knowledge_gateway is None:
            missing.append("knowledge_gateway")

    if _config_path_exists(config, "mugen", "modules", "core", "gateway", "email"):
        if injector.email_gateway is None:
            missing.append("email_gateway")

    if profile in {"web_only", "platform_full"} and "web" in active_platform_set:
        if injector.web_client is None:
            missing.append("web_client")

    if profile == "platform_full":
        if "matrix" in active_platform_set and injector.matrix_client is None:
            missing.append("matrix_client")
        if "whatsapp" in active_platform_set and injector.whatsapp_client is None:
            missing.append("whatsapp_client")
        if "web" in active_platform_set and injector.web_client is None:
            missing.append("web_client")

    if missing:
        for provider_name in missing:
            logger.error(f"Missing provider ({provider_name}).")

        raise RuntimeError("Dependency injector is missing required providers.")


def _get_provider_logger(
    injector: DependencyInjector,
    *,
    provider_name: str,
) -> ILoggingGateway | logging.Logger | None:
    """Resolve logger for provider building operations."""
    try:
        logger = injector.logging_gateway
    except AttributeError:
        logging.getLogger().error(f"Invalid injector ({provider_name}).")
        return None

    if logger is None:
        logger = logging.getLogger()
        logger.warning(f"Using root logger ({provider_name}).")

    return logger


def _resolve_provider_class(
    *,
    config: dict,
    provider_name: str,
    module_path: tuple[str, ...],
    interface: type,
    invalid_config_exceptions: tuple[type[Exception], ...] = (KeyError,),
) -> type:
    """Resolve provider class from mandatory module:Class configuration."""
    try:
        class_path_value = config
        for key in module_path:
            class_path_value = class_path_value[key]
    except invalid_config_exceptions as exc:
        raise RuntimeError(f"Invalid configuration ({provider_name}).") from exc

    module_name, class_name = _split_class_path(
        class_path_value,
        provider_name=provider_name,
    )
    try:
        module = import_module(name=module_name)
    except ModuleNotFoundError as exc:
        raise RuntimeError(f"Could not import module ({provider_name}).") from exc

    provider_class = getattr(module, class_name, None)
    if not isinstance(provider_class, type):
        raise RuntimeError(f"Valid subclass not found ({provider_name}).")
    if not issubclass(provider_class, interface):
        raise RuntimeError(f"Valid subclass not found ({provider_name}).")

    return provider_class


@dataclass(frozen=True)
class _ProviderSpec:
    """Declarative instructions for a single provider build."""

    provider_name: str
    injector_attr: str
    interface: type
    module_path: tuple[str, ...]
    constructor_bindings: tuple[tuple[str, str], ...]
    invalid_config_exceptions: tuple[type[Exception], ...] = (KeyError,)
    required_platform: str | None = None
    inactive_platform_warning: str | None = None
    required: bool = True


_PROVIDER_SPECS = {
    "logging_gateway": _ProviderSpec(
        provider_name="logging_gateway",
        injector_attr="logging_gateway",
        interface=ILoggingGateway,
        module_path=("mugen", "modules", "core", "gateway", "logging"),
        constructor_bindings=(("config", "config"),),
    ),
    "completion_gateway": _ProviderSpec(
        provider_name="completion_gateway",
        injector_attr="completion_gateway",
        interface=ICompletionGateway,
        module_path=("mugen", "modules", "core", "gateway", "completion"),
        constructor_bindings=(
            ("config", "config"),
            ("logging_gateway", "logging_gateway"),
        ),
    ),
    "email_gateway": _ProviderSpec(
        provider_name="email_gateway",
        injector_attr="email_gateway",
        interface=IEmailGateway,
        module_path=("mugen", "modules", "core", "gateway", "email"),
        constructor_bindings=(
            ("config", "config"),
            ("logging_gateway", "logging_gateway"),
        ),
        invalid_config_exceptions=(KeyError, ValueError),
        required=False,
    ),
    "ipc_service": _ProviderSpec(
        provider_name="ipc_service",
        injector_attr="ipc_service",
        interface=IIPCService,
        module_path=("mugen", "modules", "core", "service", "ipc"),
        constructor_bindings=(
            ("config", "config"),
            ("logging_gateway", "logging_gateway"),
        ),
    ),
    "keyval_storage_gateway": _ProviderSpec(
        provider_name="keyval_storage_gateway",
        injector_attr="keyval_storage_gateway",
        interface=IKeyValStorageGateway,
        module_path=("mugen", "modules", "core", "gateway", "storage", "keyval"),
        constructor_bindings=(
            ("config", "config"),
            ("logging_gateway", "logging_gateway"),
        ),
    ),
    "relational_storage_gateway": _ProviderSpec(
        provider_name="relational_storage_gateway",
        injector_attr="relational_storage_gateway",
        interface=IRelationalStorageGateway,
        module_path=("mugen", "modules", "core", "gateway", "storage", "relational"),
        constructor_bindings=(
            ("config", "config"),
            ("logging_gateway", "logging_gateway"),
        ),
    ),
    "web_runtime_store": _ProviderSpec(
        provider_name="web_runtime_store",
        injector_attr="web_runtime_store",
        interface=IWebRuntimeStore,
        module_path=("mugen", "modules", "core", "gateway", "storage", "web_runtime"),
        constructor_bindings=(
            ("config", "config"),
            ("relational_storage_gateway", "relational_storage_gateway"),
            ("logging_gateway", "logging_gateway"),
        ),
        invalid_config_exceptions=(KeyError, ValueError),
        required_platform="web",
        inactive_platform_warning="Web platform not active. Runtime store not loaded.",
    ),
    "nlp_service": _ProviderSpec(
        provider_name="nlp_service",
        injector_attr="nlp_service",
        interface=INLPService,
        module_path=("mugen", "modules", "core", "service", "nlp"),
        constructor_bindings=(("logging_gateway", "logging_gateway"),),
    ),
    "platform_service": _ProviderSpec(
        provider_name="platform_service",
        injector_attr="platform_service",
        interface=IPlatformService,
        module_path=("mugen", "modules", "core", "service", "platform"),
        constructor_bindings=(
            ("config", "config"),
            ("logging_gateway", "logging_gateway"),
        ),
    ),
    "user_service": _ProviderSpec(
        provider_name="user_service",
        injector_attr="user_service",
        interface=IUserService,
        module_path=("mugen", "modules", "core", "service", "user"),
        constructor_bindings=(
            ("keyval_storage_gateway", "keyval_storage_gateway"),
            ("logging_gateway", "logging_gateway"),
        ),
    ),
    "messaging_service": _ProviderSpec(
        provider_name="messaging_service",
        injector_attr="messaging_service",
        interface=IMessagingService,
        module_path=("mugen", "modules", "core", "service", "messaging"),
        constructor_bindings=(
            ("config", "config"),
            ("completion_gateway", "completion_gateway"),
            ("keyval_storage_gateway", "keyval_storage_gateway"),
            ("logging_gateway", "logging_gateway"),
            ("user_service", "user_service"),
        ),
    ),
    "knowledge_gateway": _ProviderSpec(
        provider_name="knowledge_gateway",
        injector_attr="knowledge_gateway",
        interface=IKnowledgeGateway,
        module_path=("mugen", "modules", "core", "gateway", "knowledge"),
        constructor_bindings=(
            ("config", "config"),
            ("logging_gateway", "logging_gateway"),
        ),
        invalid_config_exceptions=(KeyError, ValueError),
        required=False,
    ),
    "matrix_client": _ProviderSpec(
        provider_name="matrix_client",
        injector_attr="matrix_client",
        interface=IMatrixClient,
        module_path=("mugen", "modules", "core", "client", "matrix"),
        constructor_bindings=(
            ("config", "config"),
            ("ipc_service", "ipc_service"),
            ("keyval_storage_gateway", "keyval_storage_gateway"),
            ("logging_gateway", "logging_gateway"),
            ("messaging_service", "messaging_service"),
            ("user_service", "user_service"),
        ),
        invalid_config_exceptions=(KeyError, ValueError),
        required_platform="matrix",
        inactive_platform_warning="Matrix platform not active. Client not loaded.",
    ),
    "whatsapp_client": _ProviderSpec(
        provider_name="whatsapp_client",
        injector_attr="whatsapp_client",
        interface=IWhatsAppClient,
        module_path=("mugen", "modules", "core", "client", "whatsapp"),
        constructor_bindings=(
            ("config", "config"),
            ("ipc_service", "ipc_service"),
            ("keyval_storage_gateway", "keyval_storage_gateway"),
            ("logging_gateway", "logging_gateway"),
            ("messaging_service", "messaging_service"),
            ("user_service", "user_service"),
        ),
        invalid_config_exceptions=(KeyError, ValueError),
        required_platform="whatsapp",
        inactive_platform_warning="WhatsApp platform not active. Client not loaded.",
    ),
    "web_client": _ProviderSpec(
        provider_name="web_client",
        injector_attr="web_client",
        interface=IWebClient,
        module_path=("mugen", "modules", "core", "client", "web"),
        constructor_bindings=(
            ("config", "config"),
            ("ipc_service", "ipc_service"),
            ("keyval_storage_gateway", "keyval_storage_gateway"),
            ("web_runtime_store", "web_runtime_store"),
            ("logging_gateway", "logging_gateway"),
            ("messaging_service", "messaging_service"),
            ("user_service", "user_service"),
        ),
        invalid_config_exceptions=(KeyError, ValueError),
        required_platform="web",
        inactive_platform_warning="Web platform not active. Client not loaded.",
    ),
}

_PROVIDER_BUILD_ORDER = (
    "completion_gateway",
    "email_gateway",
    "ipc_service",
    "keyval_storage_gateway",
    "relational_storage_gateway",
    "web_runtime_store",
    "nlp_service",
    "platform_service",
    "user_service",
    "messaging_service",
    "knowledge_gateway",
    "matrix_client",
    "whatsapp_client",
    "web_client",
)


def _get_bootstrap_provider_logger(config: dict) -> logging.Logger:
    """Resolve a logger before a logging provider is available."""
    if isinstance(config, dict):
        mugen_cfg = config.get("mugen", {})
        logger_cfg = mugen_cfg.get("logger", {})
        logger_name = logger_cfg.get("name")
        if isinstance(logger_name, str) and logger_name.strip() != "":
            return logging.getLogger(logger_name.strip())
    return logging.getLogger()


def _build_provider_from_spec(
    config: dict,
    injector: DependencyInjector,
    *,
    spec: _ProviderSpec,
    logger: ILoggingGateway | logging.Logger,
    validate_injector_config: bool = False,
    strict_required: bool = False,
) -> None:
    """Build a provider using declarative spec metadata."""
    raise_errors = strict_required and spec.required

    if spec.required_platform is not None:
        raw_active_platforms = _get_active_platforms(config)
        normalized_active_platforms = _normalize_platforms(raw_active_platforms)
        if raw_active_platforms is None:
            message = f"Invalid configuration ({spec.provider_name})."
            if raise_errors:
                raise ProviderBootstrapError(message)
            logger.error(message)
            return

        if spec.required_platform not in normalized_active_platforms:
            if spec.inactive_platform_warning is not None:
                logger.warning(spec.inactive_platform_warning)
            return

    configured = _config_path_exists(config, *spec.module_path)
    if configured is not True:
        if spec.required is not True:
            return
        if raise_errors:
            message = (
                f"Missing required provider configuration ({spec.provider_name}) at "
                f"{'.'.join(spec.module_path)}."
            )
            raise ProviderBootstrapError(message)
        logger.error(f"Invalid configuration ({spec.provider_name}).")
        return

    configured_class_path = _config_path_value(config, *spec.module_path)

    try:
        provider_class = _resolve_provider_class(
            config=config,
            provider_name=spec.provider_name,
            module_path=spec.module_path,
            interface=spec.interface,
            invalid_config_exceptions=spec.invalid_config_exceptions,
        )
    except RuntimeError as exc:
        if raise_errors:
            message = (
                f"Provider bootstrap failed ({spec.provider_name}) "
                f"class_path={configured_class_path!r}: {exc}"
            )
            raise ProviderBootstrapError(message) from exc
        if spec.required:
            logger.error(str(exc))
        else:
            logger.warning(str(exc))
        return

    if validate_injector_config and (
        injector is None or not hasattr(injector, "config")
    ):
        message = f"Invalid injector ({spec.provider_name})."
        if raise_errors:
            raise ProviderBootstrapError(message)
        logger.error(message)
        return

    try:
        provider_kwargs = {
            arg_name: getattr(injector, injector_attr)
            for arg_name, injector_attr in spec.constructor_bindings
        }
        setattr(injector, spec.injector_attr, provider_class(**provider_kwargs))
    except AttributeError as exc:
        message = f"Invalid injector ({spec.provider_name})."
        if raise_errors:
            raise ProviderBootstrapError(message) from exc
        logger.error(message)
        logger.debug(str(exc))
    except Exception as exc:  # pylint: disable=broad-exception-caught
        message = (
            f"Provider construction failed ({spec.provider_name}) "
            f"class_path={configured_class_path!r}: {type(exc).__name__}: {exc}"
        )
        if raise_errors:
            raise ProviderBootstrapError(message) from exc
        if spec.required:
            logger.error(f"Invalid injector ({spec.provider_name}).")
        else:
            logger.warning(message)


def _build_provider(
    config: dict,
    injector: DependencyInjector,
    *,
    provider_name: str,
    strict_required: bool = False,
) -> None:
    """Build a provider by name."""
    spec = _PROVIDER_SPECS[provider_name]

    if provider_name == "logging_gateway":
        logger = _get_bootstrap_provider_logger(config)
        _build_provider_from_spec(
            config,
            injector,
            spec=spec,
            logger=logger,
            validate_injector_config=True,
            strict_required=strict_required,
        )
        return

    logger = _get_provider_logger(injector, provider_name=provider_name)
    if logger is None:
        return

    _build_provider_from_spec(
        config,
        injector,
        spec=spec,
        logger=logger,
        strict_required=strict_required,
    )


def _load_config(config_file: str) -> dict:
    """Load TOML configuration."""
    # Get application base path.
    rel = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "..")
    basedir = os.path.realpath(rel)
    # Attempt to read TOML config file.
    try:
        with open(os.path.join(basedir, config_file), "r", encoding="utf8") as f:
            config = tomlkit.loads(f.read()).value
            # Add base directory to configuration.
            config["basedir"] = basedir
            return config
    except FileNotFoundError as exc:
        raise ContainerBootstrapError(
            "Configuration file not found. "
            f"Set MUGEN_CONFIG_FILE to a valid path (received: {config_file!r})."
        ) from exc


def _resolve_config_file() -> str:
    """Resolve config file path from environment with sane defaults."""
    config_file = os.getenv("MUGEN_CONFIG_FILE", "mugen.toml")
    if not isinstance(config_file, str):
        return "mugen.toml"
    config_file = config_file.strip()
    if config_file == "":
        return "mugen.toml"
    return config_file


def _build_container() -> DependencyInjector:
    """Build providers.

    Order is important.
    """
    config = _load_config(_resolve_config_file())
    injector = DependencyInjector()

    _build_config_provider(config, injector)

    _build_provider(
        config,
        injector,
        provider_name="logging_gateway",
        strict_required=True,
    )

    for provider_name in _PROVIDER_BUILD_ORDER:
        _build_provider(
            config,
            injector,
            provider_name=provider_name,
            strict_required=True,
        )

    _validate_container(config, injector)

    return injector


def _shutdown_provider(
    provider_name: str,
    provider: object | None,
    logger: ILoggingGateway | logging.Logger,
) -> None:
    """Synchronous cleanup wrapper for non-running-loop contexts."""
    if provider is None:
        return

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(_shutdown_provider_async(provider_name, provider, logger))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(f"Failed to shutdown provider ({provider_name}): {exc}")
        return

    raise RuntimeError(
        "Synchronous provider shutdown is not allowed in a running event loop "
        f"({provider_name}); use shutdown_container_async()."
    )


async def _shutdown_provider_async(
    provider_name: str,
    provider: object | None,
    logger: ILoggingGateway | logging.Logger,
) -> None:
    """Deterministically close one provider instance."""
    if provider is None:
        return

    close = getattr(provider, "close", None)
    aclose = getattr(provider, "aclose", None)

    hooks: list[tuple[str, object]] = []
    if callable(close):
        hooks.append(("close", close))
    if callable(aclose) and aclose is not close:
        hooks.append(("aclose", aclose))

    for hook_name, hook in hooks:
        try:
            maybe_awaitable = hook()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if hook_name == "close":
                logger.warning(f"Failed to close provider ({provider_name}): {exc}")
            else:
                logger.warning(
                    f"Failed to invoke provider {hook_name} ({provider_name}): {exc}"
                )
            continue

        if inspect.isawaitable(maybe_awaitable) is not True:
            continue
        try:
            await maybe_awaitable
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if hook_name == "close":
                logger.warning(
                    f"Failed to await provider close ({provider_name}): {exc}"
                )
            else:
                logger.warning(
                    f"Failed to await provider {hook_name} ({provider_name}): {exc}"
                )


def _provider_specs_for_shutdown() -> list[_ProviderSpec]:
    """Return provider specs in reverse build order for dependency-safe cleanup."""
    ordered_specs = [spec for spec in _PROVIDER_SPECS.values()]
    return list(reversed(ordered_specs))


def _shutdown_injector(injector: DependencyInjector | None) -> None:
    """Synchronous cleanup wrapper for non-running-loop contexts."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_shutdown_injector_async(injector))
        return

    raise RuntimeError(
        "Synchronous injector shutdown is not allowed in a running event loop; "
        "use shutdown_container_async()."
    )


async def _shutdown_injector_async(injector: DependencyInjector | None) -> None:
    """Deterministically cleanup providers for an injector instance."""
    if injector is None:
        return

    logger: ILoggingGateway | logging.Logger = getattr(
        injector,
        "logging_gateway",
        logging.getLogger(),
    )

    seen: set[int] = set()
    for spec in _provider_specs_for_shutdown():
        provider = getattr(injector, spec.injector_attr, None)
        if provider is None:
            continue

        provider_id = id(provider)
        if provider_id in seen:
            setattr(injector, spec.injector_attr, None)
            continue

        seen.add(provider_id)
        await _shutdown_provider_async(spec.provider_name, provider, logger)
        setattr(injector, spec.injector_attr, None)

    try:
        ext_services = dict(getattr(injector, "ext_services", {}))
    except Exception:  # pylint: disable=broad-exception-caught
        ext_services = {}

    for name, service in ext_services.items():
        service_id = id(service)
        if service_id in seen:
            continue
        seen.add(service_id)
        await _shutdown_provider_async(f"ext_service:{name}", service, logger)


class _ContainerProxy:
    """Lazy proxy for the application-wide dependency injector."""

    def __init__(self) -> None:
        self._injector: DependencyInjector | None = None

    def build(self, *, force: bool = False) -> DependencyInjector:
        """Build and cache the injector if needed."""
        if force or self._injector is None:
            if force and self._injector is not None:
                _shutdown_injector(self._injector)
            self._injector = _build_container()
        return self._injector

    def shutdown(self) -> None:
        """Shutdown providers and clear the cached injector."""
        _shutdown_injector(self._injector)
        self._injector = None

    async def shutdown_async(self) -> None:
        """Shutdown providers asynchronously and clear cached injector."""
        await _shutdown_injector_async(self._injector)
        self._injector = None

    def reset(self) -> None:
        """Reset the cached injector."""
        self.shutdown()

    def __getattr__(self, name: str):
        return getattr(self.build(), name)

    def __setattr__(self, name: str, value) -> None:
        if name == "_injector":
            object.__setattr__(self, name, value)
            return
        setattr(self.build(), name, value)


container = _ContainerProxy()


def build_container(*, force: bool = False) -> DependencyInjector:
    """Build and cache the app-wide injector."""
    return container.build(force=force)


def reset_container() -> None:
    """Reset cached injector state (primarily for tests)."""
    container.reset()


def shutdown_container() -> None:
    """Shutdown all providers and clear the cached injector."""
    container.shutdown()


async def shutdown_container_async() -> None:
    """Shutdown all providers asynchronously and clear the cached injector."""
    await container.shutdown_async()

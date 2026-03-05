"""Provides an application-wide dependency injection container."""

__all__ = [
    "ContainerShutdownError",
    "EXT_SERVICE_ADMIN_REGISTRY",
    "EXT_SERVICE_ADMIN_SANDBOX_ENFORCER",
    "EXT_SERVICE_ADMIN_SVC_AUTH",
    "EXT_SERVICE_ADMIN_SVC_JWT",
    "ProviderShutdownFailure",
    "build_container",
    "container",
    "ensure_container_readiness_async",
    "get_container_readiness_report",
    "reset_container",
    "shutdown_container",
    "shutdown_container_async",
]

import asyncio
import inspect
import logging
import os
from dataclasses import dataclass
from types import SimpleNamespace

import tomlkit

from mugen.core.contract.client.line import ILineClient
from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.client.signal import ISignalClient
from mugen.core.contract.client.telegram import ITelegramClient
from mugen.core.contract.client.wechat import IWeChatClient
from mugen.core.contract.client.web import IWebClient
from mugen.core.contract.client.whatsapp import IWhatsAppClient
from mugen.core.contract.line_runtime_config import (
    validate_line_enabled_runtime_config,
)
from mugen.core.contract.matrix_runtime_config import (
    validate_matrix_enabled_runtime_config,
)
from mugen.core.contract.signal_runtime_config import (
    validate_signal_enabled_runtime_config,
)
from mugen.core.contract.telegram_runtime_config import (
    validate_telegram_enabled_runtime_config,
)
from mugen.core.contract.wechat_runtime_config import (
    validate_wechat_enabled_runtime_config,
)
from mugen.core.contract.runtime_bootstrap import parse_runtime_bootstrap_settings
from mugen.core.contract.gateway.completion import ICompletionGateway
from mugen.core.contract.gateway.email import IEmailGateway
from mugen.core.contract.gateway.knowledge import IKnowledgeGateway
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.gateway.storage.media import IMediaStorageGateway
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.web_runtime import IWebRuntimeStore
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.nlp import INLPService
from mugen.core.contract.service.platform import IPlatformService
from mugen.core.contract.service.user import IUserService
from mugen.core.gateway.storage.rdbms.sqla.shared_runtime import SharedSQLAlchemyRuntime
from mugen.core.utility.collection.namespace import NamespaceConfig, to_namespace
from mugen.core.utility.config_value import (
    parse_nonnegative_finite_float,
    parse_optional_positive_finite_float,
)
from mugen.core.utility.platforms import normalize_platforms, unknown_platforms
from mugen.core.utility.rdbms_schema import resolve_core_rdbms_schema

from .injector import DependencyInjector
from .provider_registry import resolve_provider_class

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


@dataclass(frozen=True, slots=True)
class ProviderShutdownFailure:
    """Structured provider shutdown failure signal."""

    provider_name: str
    hook_name: str
    reason: str


def _format_provider_shutdown_failure(failure: ProviderShutdownFailure) -> str:
    return (
        f"provider={failure.provider_name} "
        f"hook={failure.hook_name} "
        f"reason={failure.reason}"
    )


class ContainerShutdownError(RuntimeError):
    """Raised when one or more container providers fail deterministic shutdown."""

    def __init__(self, failures: tuple[ProviderShutdownFailure, ...]) -> None:
        self.failures = failures
        if not failures:
            message = "Container shutdown failed."
        else:
            message = "Container shutdown failed: " + "; ".join(
                _format_provider_shutdown_failure(failure)
                for failure in failures
            )
        super().__init__(message)


@dataclass(frozen=True)
class ProviderReadinessReport:
    """Structured provider readiness outcome for startup capability reporting."""

    successful_providers: tuple[str, ...]
    required_failures: dict[str, str]
    optional_failures: dict[str, str]


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


def _build_shared_relational_runtime(injector: DependencyInjector) -> None:
    """Build and attach shared relational SQLAlchemy resources."""
    if not isinstance(injector, DependencyInjector):
        raise RuntimeError("Invalid dependency injector instance.")
    if injector.config is None:
        raise RuntimeError("Configuration provider unavailable for relational runtime.")
    injector.relational_runtime = SharedSQLAlchemyRuntime.from_config(injector.config)


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


def _ensure_only_known_keys(
    section: dict,
    *,
    path: str,
    allowed: set[str],
) -> None:
    unknown = sorted(set(section.keys()) - allowed)
    if unknown:
        unknown_text = ", ".join(unknown)
        raise RuntimeError(
            f"Invalid configuration: unknown key(s) at {path}: {unknown_text}."
        )


def _validate_optional_positive_timeout(
    value: object,
    *,
    path: str,
) -> None:
    parse_optional_positive_finite_float(value, path)


def _validate_required_positive_timeout(
    value: object,
    *,
    path: str,
) -> None:
    if value is None or value == "":
        raise RuntimeError(
            f"Invalid configuration: {path} is required."
        )
    _validate_optional_positive_timeout(value, path=path)


def _validate_required_runtime_profile(
    value: object,
    *,
    path: str,
) -> None:
    if not isinstance(value, str):
        raise RuntimeError(
            f"Invalid configuration: {path} is required and must be platform_full."
        )
    normalized = value.strip().lower()
    if normalized != "platform_full":
        raise RuntimeError(
            f"Invalid configuration: {path} must be platform_full."
        )


def _validate_optional_nonnegative_timeout_like_value(
    value: object,
    *,
    path: str,
) -> None:
    parse_nonnegative_finite_float(
        value,
        field_name=path,
        default=0.0,
    )


def _validate_extension_entry_schema(
    entry: object,
    *,
    path: str,
) -> None:
    if not isinstance(entry, dict):
        raise RuntimeError(f"Invalid configuration: {path} entries must be tables.")
    _ensure_only_known_keys(
        entry,
        path=path,
        allowed={
            "type",
            "token",
            "enabled",
            "critical",
            "name",
            "namespace",
            "models",
            "contrib",
        },
    )
    token = entry.get("token")
    if not isinstance(token, str) or token.strip() == "":
        raise RuntimeError(
            f"Invalid configuration: {path}.token is required and must be a string."
        )
    if ":" in token:
        raise RuntimeError(
            f"Invalid configuration: {path}.token must be a token (module:Class unsupported)."
        )

    ext_type = entry.get("type")
    if ext_type is not None and not isinstance(ext_type, str):
        raise RuntimeError(
            f"Invalid configuration: {path}.type must be a string when provided."
        )


def _validate_core_module_schema(config: dict) -> None:
    resolve_core_rdbms_schema(config)

    mugen_cfg = config.get("mugen")
    if not isinstance(mugen_cfg, dict):
        raise RuntimeError("Invalid configuration: [mugen] section is required.")
    _ensure_only_known_keys(
        mugen_cfg,
        path="mugen",
        allowed={
            "assistant",
            "beta",
            "commands",
            "debug_conversation",
            "environment",
            "logger",
            "messaging",
            "modules",
            "platforms",
            "runtime",
            "storage",
        },
    )

    runtime_cfg = mugen_cfg.get("runtime")
    if not isinstance(runtime_cfg, dict):
        raise RuntimeError("Invalid configuration: mugen.runtime must be a table.")
    _ensure_only_known_keys(
        runtime_cfg,
        path="mugen.runtime",
        allowed={
            "phase_b",
            "profile",
            "provider_readiness_timeout_seconds",
            "provider_shutdown_timeout_seconds",
            "shutdown_timeout_seconds",
        },
    )
    _validate_required_runtime_profile(
        runtime_cfg.get("profile"),
        path="mugen.runtime.profile",
    )
    _validate_required_positive_timeout(
        runtime_cfg.get("provider_readiness_timeout_seconds"),
        path="mugen.runtime.provider_readiness_timeout_seconds",
    )
    _validate_required_positive_timeout(
        runtime_cfg.get("provider_shutdown_timeout_seconds"),
        path="mugen.runtime.provider_shutdown_timeout_seconds",
    )
    _validate_required_positive_timeout(
        runtime_cfg.get("shutdown_timeout_seconds"),
        path="mugen.runtime.shutdown_timeout_seconds",
    )

    phase_b_cfg = runtime_cfg.get("phase_b")
    if not isinstance(phase_b_cfg, dict):
        raise RuntimeError("Invalid configuration: mugen.runtime.phase_b must be a table.")
    _ensure_only_known_keys(
        phase_b_cfg,
        path="mugen.runtime.phase_b",
        allowed={
            "critical_platforms",
            "degrade_on_critical_exit",
            "readiness_grace_seconds",
            "startup_timeout_seconds",
            "supervisor_max_restarts",
            "supervisor_backoff_base_seconds",
            "supervisor_backoff_max_seconds",
        },
    )
    _validate_optional_nonnegative_timeout_like_value(
        phase_b_cfg.get("readiness_grace_seconds"),
        path="mugen.runtime.phase_b.readiness_grace_seconds",
    )
    _validate_required_positive_timeout(
        phase_b_cfg.get("startup_timeout_seconds"),
        path="mugen.runtime.phase_b.startup_timeout_seconds",
    )
    _validate_optional_positive_timeout(
        phase_b_cfg.get("supervisor_backoff_base_seconds"),
        path="mugen.runtime.phase_b.supervisor_backoff_base_seconds",
    )
    _validate_optional_positive_timeout(
        phase_b_cfg.get("supervisor_backoff_max_seconds"),
        path="mugen.runtime.phase_b.supervisor_backoff_max_seconds",
    )

    messaging_cfg = mugen_cfg.get("messaging")
    if not isinstance(messaging_cfg, dict):
        raise RuntimeError("Invalid configuration: mugen.messaging must be a table.")
    _ensure_only_known_keys(
        messaging_cfg,
        path="mugen.messaging",
        allowed={
            "ct_trigger_prefilter_enabled",
            "extension_timeout_seconds",
            "history_max_messages",
            "history_save_cas_retries",
            "mh_mode",
        },
    )
    mh_mode = messaging_cfg.get("mh_mode")
    if not isinstance(mh_mode, str) or mh_mode.strip() == "":
        raise RuntimeError(
            "Invalid configuration: mugen.messaging.mh_mode is required and must be "
            "'optional' or 'required'."
        )
    normalized_mh_mode = mh_mode.strip().lower()
    if normalized_mh_mode not in {"optional", "required"}:
        raise RuntimeError(
            "Invalid configuration: mugen.messaging.mh_mode is required and must be "
            "'optional' or 'required'."
        )

    modules_cfg = mugen_cfg.get("modules")
    if not isinstance(modules_cfg, dict):
        raise RuntimeError("Invalid configuration: mugen.modules must be a table.")
    _ensure_only_known_keys(
        modules_cfg,
        path="mugen.modules",
        allowed={"core", "extensions"},
    )

    core_cfg = modules_cfg.get("core")
    if not isinstance(core_cfg, dict):
        raise RuntimeError("Invalid configuration: mugen.modules.core must be a table.")
    _ensure_only_known_keys(
        core_cfg,
        path="mugen.modules.core",
        allowed={"client", "extensions", "gateway", "service"},
    )

    for section_name, allowed_keys in (
        (
            "client",
            {"line", "matrix", "signal", "telegram", "wechat", "whatsapp", "web"},
        ),
        ("service", {"ipc", "messaging", "nlp", "platform", "user"}),
    ):
        section = core_cfg.get(section_name)
        if not isinstance(section, dict):
            raise RuntimeError(
                f"Invalid configuration: mugen.modules.core.{section_name} must be a table."
            )
        _ensure_only_known_keys(
            section,
            path=f"mugen.modules.core.{section_name}",
            allowed=allowed_keys,
        )
        for provider_key, provider_token in section.items():
            if not isinstance(provider_token, str) or provider_token.strip() == "":
                raise RuntimeError(
                    "Invalid configuration: "
                    f"mugen.modules.core.{section_name}.{provider_key} must be a token string."
                )
            if ":" in provider_token:
                raise RuntimeError(
                    "Invalid configuration: "
                    f"mugen.modules.core.{section_name}.{provider_key} must be a token "
                    "(module:Class unsupported)."
                )

    gateway_cfg = core_cfg.get("gateway")
    if not isinstance(gateway_cfg, dict):
        raise RuntimeError("Invalid configuration: mugen.modules.core.gateway must be a table.")
    _ensure_only_known_keys(
        gateway_cfg,
        path="mugen.modules.core.gateway",
        allowed={"completion", "email", "knowledge", "logging", "storage"},
    )

    storage_cfg = gateway_cfg.get("storage")
    if not isinstance(storage_cfg, dict):
        raise RuntimeError(
            "Invalid configuration: mugen.modules.core.gateway.storage must be a table."
        )
    _ensure_only_known_keys(
        storage_cfg,
        path="mugen.modules.core.gateway.storage",
        allowed={"keyval", "media", "relational", "web_runtime"},
    )

    for provider_key in ("completion", "logging"):
        provider_token = gateway_cfg.get(provider_key)
        if not isinstance(provider_token, str) or provider_token.strip() == "":
            raise RuntimeError(
                "Invalid configuration: "
                f"mugen.modules.core.gateway.{provider_key} must be a token string."
            )
        if ":" in provider_token:
            raise RuntimeError(
                "Invalid configuration: "
                f"mugen.modules.core.gateway.{provider_key} must be a token "
                "(module:Class unsupported)."
            )

    for provider_key, provider_token in storage_cfg.items():
        if not isinstance(provider_token, str) or provider_token.strip() == "":
            raise RuntimeError(
                "Invalid configuration: "
                f"mugen.modules.core.gateway.storage.{provider_key} must be a token string."
            )
        if ":" in provider_token:
            raise RuntimeError(
                "Invalid configuration: "
                f"mugen.modules.core.gateway.storage.{provider_key} must be a token "
                "(module:Class unsupported)."
            )

    for optional_key in ("email", "knowledge"):
        optional_token = gateway_cfg.get(optional_key)
        if optional_token is None:
            continue
        if not isinstance(optional_token, str) or optional_token.strip() == "":
            raise RuntimeError(
                "Invalid configuration: "
                f"mugen.modules.core.gateway.{optional_key} must be a token string."
            )
        if ":" in optional_token:
            raise RuntimeError(
                "Invalid configuration: "
                f"mugen.modules.core.gateway.{optional_key} must be a token "
                "(module:Class unsupported)."
            )

    core_extensions_cfg = core_cfg.get("extensions")
    if core_extensions_cfg is None:
        core_extensions_cfg = []
    if not isinstance(core_extensions_cfg, list):
        raise RuntimeError(
            "Invalid configuration: mugen.modules.core.extensions must be an array."
        )
    for index, entry in enumerate(core_extensions_cfg):
        _validate_extension_entry_schema(
            entry,
            path=f"mugen.modules.core.extensions[{index}]",
        )

    ext_cfg = modules_cfg.get("extensions")
    if ext_cfg is None:
        ext_cfg = []
    if not isinstance(ext_cfg, list):
        raise RuntimeError(
            "Invalid configuration: mugen.modules.extensions must be an array."
        )
    for index, entry in enumerate(ext_cfg):
        _validate_extension_entry_schema(
            entry,
            path=f"mugen.modules.extensions[{index}]",
        )

    active_platforms = normalize_platforms(mugen_cfg.get("platforms", []))
    if "line" in active_platforms:
        validate_line_enabled_runtime_config(config)
    if "matrix" in active_platforms:
        validate_matrix_enabled_runtime_config(config)
    if "signal" in active_platforms:
        validate_signal_enabled_runtime_config(config)
    if "telegram" in active_platforms:
        validate_telegram_enabled_runtime_config(config)
    if "wechat" in active_platforms:
        validate_wechat_enabled_runtime_config(config)


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
    settings = parse_runtime_bootstrap_settings(config)
    return str(settings.profile)


def _validate_container(config: dict, injector: DependencyInjector) -> None:
    """Validate that required providers were built for active configuration."""
    profile = _resolve_runtime_profile_override(config)
    active_platforms = _normalize_platforms(_get_active_platforms(config))
    active_platform_set = set(active_platforms)
    unsupported_platforms = unknown_platforms(active_platforms)

    logger = injector.logging_gateway
    if logger is None:
        logger = logging.getLogger()

    if unsupported_platforms:
        unsupported_platforms_text = ", ".join(unsupported_platforms)
        logger.error(
            "Unsupported platform configuration detected: "
            f"{unsupported_platforms_text}."
        )
        raise RuntimeError(
            "Unsupported platform configuration: "
            f"{unsupported_platforms_text}. "
            "Allowed values are line, matrix, signal, telegram, wechat, web, whatsapp."
        )

    if profile != "platform_full":
        logger.error(
            "Runtime profile platform_full is required."
        )
        raise RuntimeError(
            "Runtime profile platform_full is required."
        )

    if not active_platforms:
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
        required.append("media_storage_gateway")
        required.append("relational_storage_gateway")
        required.append("web_runtime_store")

    missing = [name for name in required if getattr(injector, name) is None]

    if _config_path_exists(config, "mugen", "modules", "core", "gateway", "knowledge"):
        if injector.knowledge_gateway is None:
            missing.append("knowledge_gateway")

    if _config_path_exists(config, "mugen", "modules", "core", "gateway", "email"):
        if injector.email_gateway is None:
            missing.append("email_gateway")

    if "web" in active_platform_set:
        if injector.web_client is None:
            missing.append("web_client")

    if "matrix" in active_platform_set and injector.matrix_client is None:
        missing.append("matrix_client")
    if "line" in active_platform_set and injector.line_client is None:
        missing.append("line_client")
    if "signal" in active_platform_set and injector.signal_client is None:
        missing.append("signal_client")
    if "telegram" in active_platform_set and injector.telegram_client is None:
        missing.append("telegram_client")
    if "wechat" in active_platform_set and injector.wechat_client is None:
        missing.append("wechat_client")
    if "whatsapp" in active_platform_set and injector.whatsapp_client is None:
        missing.append("whatsapp_client")

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
    """Resolve provider class from strict provider token configuration."""
    try:
        provider_token = config
        for key in module_path:
            provider_token = provider_token[key]
    except invalid_config_exceptions as exc:
        raise RuntimeError(f"Invalid configuration ({provider_name}).") from exc

    return resolve_provider_class(
        provider_name=provider_name,
        token=provider_token,
        interface=interface,
    )


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
    readiness_required: bool = True


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
        readiness_required=False,
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
            ("relational_runtime", "relational_runtime"),
        ),
    ),
    "media_storage_gateway": _ProviderSpec(
        provider_name="media_storage_gateway",
        injector_attr="media_storage_gateway",
        interface=IMediaStorageGateway,
        module_path=("mugen", "modules", "core", "gateway", "storage", "media"),
        constructor_bindings=(
            ("config", "config"),
            ("keyval_storage_gateway", "keyval_storage_gateway"),
            ("logging_gateway", "logging_gateway"),
        ),
        invalid_config_exceptions=(KeyError, ValueError),
        required_platform="web",
        inactive_platform_warning="Web platform not active. Media storage gateway not loaded.",
    ),
    "relational_storage_gateway": _ProviderSpec(
        provider_name="relational_storage_gateway",
        injector_attr="relational_storage_gateway",
        interface=IRelationalStorageGateway,
        module_path=("mugen", "modules", "core", "gateway", "storage", "relational"),
        constructor_bindings=(
            ("config", "config"),
            ("logging_gateway", "logging_gateway"),
            ("relational_runtime", "relational_runtime"),
        ),
    ),
    "web_runtime_store": _ProviderSpec(
        provider_name="web_runtime_store",
        injector_attr="web_runtime_store",
        interface=IWebRuntimeStore,
        module_path=("mugen", "modules", "core", "gateway", "storage", "web_runtime"),
        constructor_bindings=(
            ("config", "config"),
            ("logging_gateway", "logging_gateway"),
            ("relational_runtime", "relational_runtime"),
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
        readiness_required=False,
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
    "line_client": _ProviderSpec(
        provider_name="line_client",
        injector_attr="line_client",
        interface=ILineClient,
        module_path=("mugen", "modules", "core", "client", "line"),
        constructor_bindings=(
            ("config", "config"),
            ("ipc_service", "ipc_service"),
            ("keyval_storage_gateway", "keyval_storage_gateway"),
            ("logging_gateway", "logging_gateway"),
            ("messaging_service", "messaging_service"),
            ("user_service", "user_service"),
        ),
        invalid_config_exceptions=(KeyError, ValueError),
        required_platform="line",
        inactive_platform_warning="LINE platform not active. Client not loaded.",
    ),
    "signal_client": _ProviderSpec(
        provider_name="signal_client",
        injector_attr="signal_client",
        interface=ISignalClient,
        module_path=("mugen", "modules", "core", "client", "signal"),
        constructor_bindings=(
            ("config", "config"),
            ("ipc_service", "ipc_service"),
            ("keyval_storage_gateway", "keyval_storage_gateway"),
            ("logging_gateway", "logging_gateway"),
            ("messaging_service", "messaging_service"),
            ("user_service", "user_service"),
        ),
        invalid_config_exceptions=(KeyError, ValueError),
        required_platform="signal",
        inactive_platform_warning="Signal platform not active. Client not loaded.",
    ),
    "telegram_client": _ProviderSpec(
        provider_name="telegram_client",
        injector_attr="telegram_client",
        interface=ITelegramClient,
        module_path=("mugen", "modules", "core", "client", "telegram"),
        constructor_bindings=(
            ("config", "config"),
            ("ipc_service", "ipc_service"),
            ("keyval_storage_gateway", "keyval_storage_gateway"),
            ("logging_gateway", "logging_gateway"),
            ("messaging_service", "messaging_service"),
            ("user_service", "user_service"),
        ),
        invalid_config_exceptions=(KeyError, ValueError),
        required_platform="telegram",
        inactive_platform_warning="Telegram platform not active. Client not loaded.",
    ),
    "wechat_client": _ProviderSpec(
        provider_name="wechat_client",
        injector_attr="wechat_client",
        interface=IWeChatClient,
        module_path=("mugen", "modules", "core", "client", "wechat"),
        constructor_bindings=(
            ("config", "config"),
            ("ipc_service", "ipc_service"),
            ("keyval_storage_gateway", "keyval_storage_gateway"),
            ("logging_gateway", "logging_gateway"),
            ("messaging_service", "messaging_service"),
            ("user_service", "user_service"),
        ),
        invalid_config_exceptions=(KeyError, ValueError),
        required_platform="wechat",
        inactive_platform_warning="WeChat platform not active. Client not loaded.",
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
            ("media_storage_gateway", "media_storage_gateway"),
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
    "media_storage_gateway",
    "relational_storage_gateway",
    "web_runtime_store",
    "nlp_service",
    "platform_service",
    "user_service",
    "messaging_service",
    "knowledge_gateway",
    "matrix_client",
    "line_client",
    "signal_client",
    "telegram_client",
    "wechat_client",
    "whatsapp_client",
    "web_client",
)


def _configured_token_for_spec(config: dict, spec: _ProviderSpec) -> object:
    return _config_path_value(config, *spec.module_path)


def _resolve_readiness_provider_names(config: dict) -> list[str]:
    """Resolve providers that must pass readiness before bootstrap succeeds."""
    settings = parse_runtime_bootstrap_settings(config)
    active_platforms = list(settings.active_platforms)
    web_active = "web" in active_platforms

    readiness_provider_names: list[str] = [
        "completion_gateway",
        "keyval_storage_gateway",
    ]

    media_configured = _config_path_exists(
        config,
        "mugen",
        "modules",
        "core",
        "gateway",
        "storage",
        "media",
    )
    if media_configured and web_active:
        readiness_provider_names.append("media_storage_gateway")

    relational_configured = _config_path_exists(
        config,
        "mugen",
        "modules",
        "core",
        "gateway",
        "storage",
        "relational",
    )
    relational_required = (
        relational_configured is True
        or web_active
    )
    if relational_required:
        readiness_provider_names.append("relational_storage_gateway")

    if web_active:
        readiness_provider_names.append("web_runtime_store")

    if _config_path_exists(config, "mugen", "modules", "core", "gateway", "email"):
        readiness_provider_names.append("email_gateway")

    if _config_path_exists(
        config,
        "mugen",
        "modules",
        "core",
        "gateway",
        "knowledge",
    ):
        readiness_provider_names.append("knowledge_gateway")

    return list(dict.fromkeys(readiness_provider_names))


def _resolve_provider_readiness_timeout_seconds(config: dict) -> float:
    settings = parse_runtime_bootstrap_settings(config)
    return float(settings.provider_readiness_timeout_seconds)


def _resolve_provider_shutdown_timeout_seconds(config: dict) -> float:
    settings = parse_runtime_bootstrap_settings(config)
    return float(settings.provider_shutdown_timeout_seconds)


def _resolve_shutdown_timeout_seconds(config: dict) -> float:
    settings = parse_runtime_bootstrap_settings(config)
    return float(settings.shutdown_timeout_seconds)


async def _await_readiness_probe_async(
    maybe_awaitable,
    *,
    provider_name: str,
    configured_token: object,
    timeout_seconds: float,
) -> None:
    if inspect.isawaitable(maybe_awaitable) is not True:
        raise ProviderBootstrapError(
            "Provider readiness failed "
            f"({provider_name}) token={configured_token!r} stage=readiness: "
            "check_readiness must return an awaitable."
        )
    try:
        await asyncio.wait_for(maybe_awaitable, timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise ProviderBootstrapError(
            "Provider readiness failed "
            f"({provider_name}) token={configured_token!r} stage=readiness: "
            f"TimeoutError: readiness timed out after {timeout_seconds:.2f}s"
        ) from exc


async def _ensure_injector_readiness_async(
    config: dict,
    injector: DependencyInjector,
) -> ProviderReadinessReport:
    """Run required provider readiness checks before runtime validation."""
    timeout_seconds = _resolve_provider_readiness_timeout_seconds(config)
    successful_providers: list[str] = []
    required_failures: dict[str, str] = {}
    optional_failures: dict[str, str] = {}

    for provider_name in _resolve_readiness_provider_names(config):
        spec = _PROVIDER_SPECS[provider_name]
        configured_token = _configured_token_for_spec(config, spec)
        failure_message: str | None = None
        provider = getattr(injector, spec.injector_attr, None)
        if provider is None:
            failure_message = (
                "Provider readiness failed "
                f"({provider_name}) token={configured_token!r} stage=readiness: "
                "provider instance is unavailable."
            )
        else:
            check_readiness = getattr(provider, "check_readiness", None)
            if callable(check_readiness) is not True:
                failure_message = (
                    "Provider readiness failed "
                    f"({provider_name}) token={configured_token!r} stage=readiness: "
                    "check_readiness is unavailable."
                )
            else:
                try:
                    await _await_readiness_probe_async(
                        check_readiness(),
                        provider_name=provider_name,
                        configured_token=configured_token,
                        timeout_seconds=timeout_seconds,
                    )
                except ProviderBootstrapError as exc:
                    failure_message = str(exc)
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    failure_message = (
                        "Provider readiness failed "
                        f"({provider_name}) token={configured_token!r} stage=readiness: "
                        f"{type(exc).__name__}: {exc}"
                    )

        if failure_message is None:
            successful_providers.append(provider_name)
            continue

        if spec.readiness_required:
            required_failures[provider_name] = failure_message
            continue
        optional_failures[provider_name] = failure_message

    return ProviderReadinessReport(
        successful_providers=tuple(successful_providers),
        required_failures=required_failures,
        optional_failures=optional_failures,
    )


def _format_required_readiness_failure_message(
    report: ProviderReadinessReport,
) -> str:
    failures = report.required_failures
    if not failures:
        return "Provider readiness failed."
    messages = [failures[name] for name in sorted(failures.keys())]
    return "; ".join(messages)


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
                f"{'.'.join(spec.module_path)} stage=build."
            )
            raise ProviderBootstrapError(message)
        logger.error(f"Invalid configuration ({spec.provider_name}).")
        return

    configured_token = _config_path_value(config, *spec.module_path)

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
                f"token={configured_token!r} stage=build: {exc}"
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

    requires_relational_runtime = any(
        injector_attr == "relational_runtime"
        for _arg_name, injector_attr in spec.constructor_bindings
    )
    if requires_relational_runtime and getattr(injector, "relational_runtime", None) is None:
        try:
            _build_shared_relational_runtime(injector)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            message = (
                f"Provider bootstrap failed ({spec.provider_name}) "
                f"token={configured_token!r} stage=build: "
                f"{type(exc).__name__}: {exc}"
            )
            if raise_errors:
                raise ProviderBootstrapError(message) from exc
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
            f"token={configured_token!r} stage=build: "
            f"{type(exc).__name__}: {exc}"
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
    _validate_core_module_schema(config)
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
        failures = asyncio.run(_shutdown_provider_async(provider_name, provider, logger))
        if failures:
            raise ContainerShutdownError(failures)
        return

    raise RuntimeError(
        "Synchronous provider shutdown is not allowed in a running event loop "
        f"({provider_name}); use shutdown_container_async()."
    )


async def _shutdown_provider_async(
    provider_name: str,
    provider: object | None,
    logger: ILoggingGateway | logging.Logger,
    *,
    timeout_seconds: float | None = None,
) -> tuple[ProviderShutdownFailure, ...]:
    """Deterministically close one provider instance."""
    if provider is None:
        return ()

    close = getattr(provider, "close", None)
    aclose = getattr(provider, "aclose", None)

    hooks: list[tuple[str, object]] = []
    if callable(close):
        hooks.append(("close", close))
    if callable(aclose) and aclose is not close:
        hooks.append(("aclose", aclose))

    failures: list[ProviderShutdownFailure] = []

    for hook_name, hook in hooks:
        try:
            maybe_awaitable = hook()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            failures.append(
                ProviderShutdownFailure(
                    provider_name=provider_name,
                    hook_name=hook_name,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        if inspect.isawaitable(maybe_awaitable) is not True:
            continue
        try:
            if timeout_seconds is None:
                await maybe_awaitable
            else:
                await asyncio.wait_for(maybe_awaitable, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            timeout_reason = (
                "TimeoutError: provider shutdown timed out."
                if timeout_seconds is None
                else (
                    "TimeoutError: provider shutdown timed out after "
                    f"{timeout_seconds:.2f}s"
                )
            )
            failures.append(
                ProviderShutdownFailure(
                    provider_name=provider_name,
                    hook_name=hook_name,
                    reason=timeout_reason,
                )
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            failures.append(
                ProviderShutdownFailure(
                    provider_name=provider_name,
                    hook_name=hook_name,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            )
    return tuple(failures)


def _provider_specs_for_shutdown() -> list[_ProviderSpec]:
    """Return provider specs in reverse build order for dependency-safe cleanup."""
    ordered_provider_names = ("logging_gateway",) + _PROVIDER_BUILD_ORDER
    return [
        _PROVIDER_SPECS[provider_name]
        for provider_name in reversed(ordered_provider_names)
    ]


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
    try:
        config = _injector_config_dict(injector)
    except RuntimeError:
        # Some tests inject placeholder objects into container cache to verify
        # proxy behavior; those objects have no runtime config and no providers
        # to deterministically shut down.
        return
    provider_timeout_seconds = _resolve_provider_shutdown_timeout_seconds(config)
    shutdown_timeout_seconds = _resolve_shutdown_timeout_seconds(config)
    failures: list[ProviderShutdownFailure] = []
    failed_provider_ids: set[int] = set()

    async def _shutdown_inner() -> None:
        seen: set[int] = set()
        for spec in _provider_specs_for_shutdown():
            provider = getattr(injector, spec.injector_attr, None)
            if provider is None:
                continue

            provider_id = id(provider)
            if provider_id in seen:
                if provider_id not in failed_provider_ids:
                    setattr(injector, spec.injector_attr, None)
                continue

            seen.add(provider_id)
            provider_failures = await _shutdown_provider_async(
                spec.provider_name,
                provider,
                logger,
                timeout_seconds=provider_timeout_seconds,
            )
            if provider_failures:
                failures.extend(provider_failures)
                failed_provider_ids.add(provider_id)
                continue
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
            provider_failures = await _shutdown_provider_async(
                f"ext_service:{name}",
                service,
                logger,
                timeout_seconds=provider_timeout_seconds,
            )
            if provider_failures:
                failures.extend(provider_failures)
                failed_provider_ids.add(service_id)

        relational_runtime = getattr(injector, "relational_runtime", None)
        if relational_runtime is not None and id(relational_runtime) not in seen:
            seen.add(id(relational_runtime))
            provider_failures = await _shutdown_provider_async(
                "relational_runtime",
                relational_runtime,
                logger,
                timeout_seconds=provider_timeout_seconds,
            )
            if provider_failures:
                failures.extend(provider_failures)
                failed_provider_ids.add(id(relational_runtime))
            else:
                injector.relational_runtime = None

    try:
        await asyncio.wait_for(_shutdown_inner(), timeout=shutdown_timeout_seconds)
    except asyncio.TimeoutError as exc:
        failures.append(
            ProviderShutdownFailure(
                provider_name="injector",
                hook_name="shutdown",
                reason=(
                    "TimeoutError: injector shutdown timed out after "
                    f"{shutdown_timeout_seconds:.2f}s"
                ),
            )
        )
        for failure in failures:
            logger.error(_format_provider_shutdown_failure(failure))
        raise ContainerShutdownError(tuple(failures)) from exc

    if failures:
        for failure in failures:
            logger.error(_format_provider_shutdown_failure(failure))
        raise ContainerShutdownError(tuple(failures))


def _injector_config_dict(injector: DependencyInjector | None) -> dict:
    if injector is None:
        raise RuntimeError("Container is not built.")
    config_ns = getattr(injector, "config", None)
    config_dict = getattr(config_ns, "dict", None)
    if not isinstance(config_dict, dict):
        raise RuntimeError("Configuration dict is unavailable in container config.")
    return config_dict


class _ContainerProxy:
    """Lazy proxy for the application-wide dependency injector."""

    def __init__(self) -> None:
        self._injector: DependencyInjector | None = None
        self._readiness_checked: bool = False
        self._last_readiness_report: ProviderReadinessReport | None = None

    def build(self, *, force: bool = False) -> DependencyInjector:
        """Build and cache the injector if needed."""
        if force or self._injector is None:
            if force and self._injector is not None:
                _shutdown_injector(self._injector)
            self._injector = _build_container()
            self._readiness_checked = False
            self._last_readiness_report = None
        return self._injector

    async def ensure_readiness(self) -> DependencyInjector:
        """Ensure required provider readiness checks pass for cached injector."""
        injector = self.build()
        if self._readiness_checked:
            return injector
        try:
            config = _injector_config_dict(injector)
            readiness_report = await _ensure_injector_readiness_async(config, injector)
            self._last_readiness_report = readiness_report
            if readiness_report.required_failures:
                raise ProviderBootstrapError(
                    _format_required_readiness_failure_message(readiness_report)
                )
            _validate_container(config, injector)
        except ProviderBootstrapError:
            raise
        except RuntimeError as exc:
            raise ProviderBootstrapError(
                f"Provider readiness bootstrap configuration failed: {exc}"
            ) from exc
        self._readiness_checked = True
        return injector

    def get_readiness_report(self) -> ProviderReadinessReport | None:
        """Return the latest provider-readiness report for the cached injector."""
        return self._last_readiness_report

    def shutdown(self) -> None:
        """Shutdown providers and clear the cached injector."""
        _shutdown_injector(self._injector)
        self._injector = None
        self._readiness_checked = False
        self._last_readiness_report = None

    async def shutdown_async(self) -> None:
        """Shutdown providers asynchronously and clear cached injector."""
        await _shutdown_injector_async(self._injector)
        self._injector = None
        self._readiness_checked = False
        self._last_readiness_report = None

    def reset(self) -> None:
        """Reset the cached injector."""
        self.shutdown()

    def __getattr__(self, name: str):
        return getattr(self.build(), name)

    def __setattr__(self, name: str, value) -> None:
        if name in {"_injector", "_readiness_checked", "_last_readiness_report"}:
            object.__setattr__(self, name, value)
            return
        setattr(self.build(), name, value)


container = _ContainerProxy()


def build_container(*, force: bool = False) -> DependencyInjector:
    """Build and cache the app-wide injector."""
    return container.build(force=force)


async def ensure_container_readiness_async() -> DependencyInjector:
    """Ensure required provider readiness checks pass for cached injector."""
    return await container.ensure_readiness()


def get_container_readiness_report() -> ProviderReadinessReport | None:
    """Return latest provider readiness report for startup capability tracking."""
    return container.get_readiness_report()


def reset_container() -> None:
    """Reset cached injector state (primarily for tests)."""
    container.reset()


def shutdown_container() -> None:
    """Shutdown all providers and clear the cached injector."""
    container.shutdown()


async def shutdown_container_async() -> None:
    """Shutdown all providers asynchronously and clear the cached injector."""
    await container.shutdown_async()

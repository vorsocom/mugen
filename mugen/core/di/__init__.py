"""Provides an application-wide dependency injection container."""

__all__ = [
    "EXT_SERVICE_ADMIN_REGISTRY",
    "EXT_SERVICE_ADMIN_SVC_AUTH",
    "EXT_SERVICE_ADMIN_SVC_JWT",
    "build_container",
    "container",
    "reset_container",
]

from importlib import import_module
import logging
import os
import sys
from dataclasses import dataclass
from types import SimpleNamespace

import tomlkit

from mugen.core.contract.client.telnet import ITelnetClient
from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.client.whatsapp import IWhatsAppClient
from mugen.core.contract.gateway.completion import ICompletionGateway
from mugen.core.contract.gateway.knowledge import IKnowledgeGateway
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.nlp import INLPService
from mugen.core.contract.service.platform import IPlatformService
from mugen.core.contract.service.user import IUserService

from .injector import DependencyInjector

EXT_SERVICE_ADMIN_REGISTRY = "admin_registry"
EXT_SERVICE_ADMIN_SVC_JWT = "admin_svc_jwt"
EXT_SERVICE_ADMIN_SVC_AUTH = "admin_svc_auth"


def _nested_namespace_from_dict(items: dict, ns: SimpleNamespace) -> None:
    """Convert a nested dict to a nested SimpleNamespace"""
    # If null values are passed, this try-except
    # will catch the AttributeError that results
    # from calling items.keys().
    try:  # pylint: disable=too-many-nested-blocks
        for key in items.keys():
            # If it's a dict, recurse.
            # Also place the original dict alongside
            # the namespace as an attribute called "dict".
            if isinstance(items[key], dict):
                nested_space = SimpleNamespace()
                _nested_namespace_from_dict(items[key], nested_space)
                setattr(ns, key, nested_space)
                setattr(ns, "dict", items)
                continue

            # Handle list of dicts.
            if isinstance(items[key], list):
                # try-except for empty list.
                try:
                    if isinstance(items[key][0], dict):
                        space_list = []
                        for list_item in items[key]:
                            nested_space = SimpleNamespace()
                            _nested_namespace_from_dict(list_item, nested_space)
                            space_list.append(nested_space)
                        setattr(ns, key, space_list)
                        continue
                except IndexError:
                    # Empty barrel. No noise though.
                    pass

            # Flat item.
            setattr(ns, key, items[key])
    except AttributeError:
        # If you don't stand for something,
        # you'll fall for anything. And nothing,
        # in this case.
        pass


def _build_config_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """Build configuration provider object for DI container."""
    ns = SimpleNamespace()
    _nested_namespace_from_dict(config, ns)
    try:
        injector.config = ns
    except AttributeError:
        # System cannot run without configuration.
        # We can get here due to a null or any other
        # incorrectly typed injector.
        sys.exit(1)


def _get_provider_class(
    *,
    interface: type,
    module_name: str,
    provider_name: str,
    logger: ILoggingGateway | logging.Logger,
) -> type | None:
    """Resolve a provider implementation class for the configured module."""
    subclasses = interface.__subclasses__()
    module_matches = [x for x in subclasses if x.__module__ == module_name]

    if len(module_matches) == 1:
        return module_matches[0]

    if len(module_matches) > 1:
        logger.error(f"Multiple valid subclasses found ({provider_name}).")
        return None

    logger.error(f"Valid subclass not found ({provider_name}).")
    return None


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


def _get_active_platforms(config: dict) -> list[str] | None:
    """Get configured platform list from app configuration."""
    try:
        platforms = config["mugen"]["platforms"]
    except (KeyError, TypeError):
        return None

    if not isinstance(platforms, list):
        return None

    return platforms


def _validate_container(config: dict, injector: DependencyInjector) -> None:
    """Validate that required providers were built for active configuration."""
    required = [
        "config",
        "logging_gateway",
        "completion_gateway",
        "ipc_service",
        "keyval_storage_gateway",
        "relational_storage_gateway",
        "nlp_service",
        "platform_service",
        "user_service",
        "messaging_service",
    ]
    missing = [name for name in required if getattr(injector, name) is None]

    if _config_path_exists(config, "mugen", "modules", "core", "gateway", "knowledge"):
        if injector.knowledge_gateway is None:
            missing.append("knowledge_gateway")

    active_platforms = config.get("mugen", {}).get("platforms", [])
    if "matrix" in active_platforms and injector.matrix_client is None:
        missing.append("matrix_client")
    if "telnet" in active_platforms and injector.telnet_client is None:
        missing.append("telnet_client")
    if "whatsapp" in active_platforms and injector.whatsapp_client is None:
        missing.append("whatsapp_client")

    if missing:
        logger = injector.logging_gateway
        if logger is None:
            logger = logging.getLogger()

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


def _import_provider_module(
    *,
    config: dict,
    provider_name: str,
    module_path: tuple[str, ...],
    logger: ILoggingGateway | logging.Logger,
    invalid_config_exceptions: tuple[type[Exception], ...] = (KeyError,),
) -> str | None:
    """Resolve and import provider module from configuration path."""
    try:
        module_name = config
        for key in module_path:
            module_name = module_name[key]
    except invalid_config_exceptions:
        logger.error(f"Invalid configuration ({provider_name}).")
        return None

    try:
        import_module(name=module_name)
    except ModuleNotFoundError:
        logger.error(f"Could not import module ({provider_name}).")
        return None

    return module_name


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
    "ipc_service": _ProviderSpec(
        provider_name="ipc_service",
        injector_attr="ipc_service",
        interface=IIPCService,
        module_path=("mugen", "modules", "core", "service", "ipc"),
        constructor_bindings=(("logging_gateway", "logging_gateway"),),
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
    "telnet_client": _ProviderSpec(
        provider_name="telnet_client",
        injector_attr="telnet_client",
        interface=ITelnetClient,
        module_path=("mugen", "modules", "core", "client", "telnet"),
        constructor_bindings=(
            ("config", "config"),
            ("ipc_service", "ipc_service"),
            ("keyval_storage_gateway", "keyval_storage_gateway"),
            ("logging_gateway", "logging_gateway"),
            ("messaging_service", "messaging_service"),
            ("user_service", "user_service"),
        ),
        invalid_config_exceptions=(KeyError, ValueError),
        required_platform="telnet",
        inactive_platform_warning="Telnet platform not active. Client not loaded.",
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
}

_PROVIDER_BUILD_ORDER = (
    "completion_gateway",
    "ipc_service",
    "keyval_storage_gateway",
    "relational_storage_gateway",
    "nlp_service",
    "platform_service",
    "user_service",
    "messaging_service",
    "knowledge_gateway",
    "matrix_client",
    "telnet_client",
    "whatsapp_client",
)


def _get_bootstrap_provider_logger(config: dict) -> logging.Logger:
    """Resolve a logger before a logging provider is available."""
    try:
        return logging.getLogger(config.mugen.logger.name)
    except AttributeError:
        return logging.getLogger()


def _build_provider_from_spec(
    config: dict,
    injector: DependencyInjector,
    *,
    spec: _ProviderSpec,
    logger: ILoggingGateway | logging.Logger,
    validate_injector_config: bool = False,
) -> None:
    """Build a provider using declarative spec metadata."""
    if spec.required_platform is not None:
        active_platforms = _get_active_platforms(config)
        if active_platforms is None:
            logger.error(f"Invalid configuration ({spec.provider_name}).")
            return

        if spec.required_platform not in active_platforms:
            if spec.inactive_platform_warning is not None:
                logger.warning(spec.inactive_platform_warning)
            return

    module_name = _import_provider_module(
        config=config,
        provider_name=spec.provider_name,
        module_path=spec.module_path,
        logger=logger,
        invalid_config_exceptions=spec.invalid_config_exceptions,
    )
    if module_name is None:
        return

    if validate_injector_config and (
        injector is None or not hasattr(injector, "config")
    ):
        logger.error(f"Invalid injector ({spec.provider_name}).")
        return

    provider_class = _get_provider_class(
        interface=spec.interface,
        module_name=module_name,
        provider_name=spec.provider_name,
        logger=logger,
    )
    if provider_class is None:
        return

    try:
        provider_kwargs = {
            arg_name: getattr(injector, injector_attr)
            for arg_name, injector_attr in spec.constructor_bindings
        }
        setattr(injector, spec.injector_attr, provider_class(**provider_kwargs))
    except AttributeError:
        logger.error(f"Invalid injector ({spec.provider_name}).")


def _build_provider(
    config: dict,
    injector: DependencyInjector,
    *,
    provider_name: str,
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
    except FileNotFoundError:
        # Exit application if config file not found.
        sys.exit(1)


def _build_container() -> DependencyInjector:
    """Build providers.

    Order is important.
    """
    config = _load_config("mugen.toml")
    injector = DependencyInjector()

    _build_config_provider(config, injector)

    _build_provider(config, injector, provider_name="logging_gateway")

    for provider_name in _PROVIDER_BUILD_ORDER:
        _build_provider(config, injector, provider_name=provider_name)

    _validate_container(config, injector)

    return injector


class _ContainerProxy:
    """Lazy proxy for the application-wide dependency injector."""

    def __init__(self) -> None:
        self._injector: DependencyInjector | None = None

    def build(self, *, force: bool = False) -> DependencyInjector:
        """Build and cache the injector if needed."""
        if force or self._injector is None:
            self._injector = _build_container()
        return self._injector

    def reset(self) -> None:
        """Reset the cached injector."""
        self._injector = None

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

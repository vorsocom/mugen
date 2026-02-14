"""Provides an application-wide dependency injection container."""

__all__ = ["build_container", "container", "reset_container"]

from importlib import import_module
import logging
import os
import sys
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
    """Resolve a provider implementation class for the configured module.
    """
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


def _build_logging_gateway_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """Build logging gateway provider for DI container."""
    try:
        logger = logging.getLogger(config.mugen.logger.name)
    except AttributeError:
        logger = logging.getLogger()

    try:
        try:
            import_module(name=config["mugen"]["modules"]["core"]["gateway"]["logging"])
        except KeyError:
            logger.error("Invalid configuration (logging_gateway).")
            return
    except ModuleNotFoundError:
        # This could fail due to missing configuration values or
        # invalid module paths. Either way, no need to continue
        # if it fails.
        logger.error("Could not import module (logging_gateway).")
        return

    if injector is None or not hasattr(injector, "config"):
        logger.error("Invalid injector (logging_gateway).")
        return

    provider_class = _get_provider_class(
        interface=ILoggingGateway,
        module_name=config["mugen"]["modules"]["core"]["gateway"]["logging"],
        provider_name="logging_gateway",
        logger=logger,
    )
    if provider_class is None:
        return

    try:
        injector.logging_gateway = provider_class(
            config=injector.config,
        )
    except AttributeError:
        # We'll get an AttributeError if injector
        # is incorrectly typed.
        logger.error("Invalid injector (logging_gateway).")
        return


def _build_completion_gateway_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """Build completion gateway provider for DI container."""
    # Get logger.
    try:
        logger = injector.logging_gateway
    except AttributeError:
        # We'll get an AttributeError if injector
        # is incorrectly typed.
        logging.getLogger().error("Invalid injector (completion_gateway).")
        return

    if logger is None:
        logger = logging.getLogger()
        logger.warning("Using root logger (completion_gateway).")

    try:
        try:
            import_module(
                name=config["mugen"]["modules"]["core"]["gateway"]["completion"]
            )
        except KeyError:
            logger.error("Invalid configuration (completion_gateway).")
            return
    except ModuleNotFoundError:
        # This could fail due to missing configuration values or
        # invalid module paths. Either way, no need to continue
        # if it fails.
        logger.error("Could not import module (completion_gateway).")
        return

    provider_class = _get_provider_class(
        interface=ICompletionGateway,
        module_name=config["mugen"]["modules"]["core"]["gateway"]["completion"],
        provider_name="completion_gateway",
        logger=logger,
    )
    if provider_class is None:
        return

    injector.completion_gateway = provider_class(
        config=injector.config,
        logging_gateway=injector.logging_gateway,
    )


def _build_ipc_service_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """Build IPC service provider for DI container."""
    # Get logger.
    try:
        logger = injector.logging_gateway
    except AttributeError:
        # We'll get an AttributeError if injector
        # is incorrectly typed.
        logging.getLogger().error("Invalid injector (ipc_service).")
        return

    if logger is None:
        logger = logging.getLogger()
        logger.warning("Using root logger (ipc_service).")

    try:
        try:
            import_module(name=config["mugen"]["modules"]["core"]["service"]["ipc"])
        except KeyError:
            logger.error("Invalid configuration (ipc_service).")
            return
    except ModuleNotFoundError:
        # This could fail due to missing configuration values or
        # invalid module paths. Either way, no need to continue
        # if it fails.
        logger.error("Could not import module (ipc_service).")
        return

    provider_class = _get_provider_class(
        interface=IIPCService,
        module_name=config["mugen"]["modules"]["core"]["service"]["ipc"],
        provider_name="ipc_service",
        logger=logger,
    )
    if provider_class is None:
        return

    injector.ipc_service = provider_class(
        logging_gateway=injector.logging_gateway,
    )


def _build_keyval_storage_gateway_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """Build key-value storage gateway provider for DI container."""
    # Get logger.
    try:
        logger = injector.logging_gateway
    except AttributeError:
        # We'll get an AttributeError if injector
        # is incorrectly typed.
        logging.getLogger().error("Invalid injector (keyval_storage_gateway).")
        return

    if logger is None:
        logger = logging.getLogger()
        logger.warning("Using root logger (keyval_storage_gateway).")

    try:
        try:
            import_module(
                name=config["mugen"]["modules"]["core"]["gateway"]["storage"]["keyval"]
            )
        except KeyError:
            logger.error("Invalid configuration (keyval_storage_gateway).")
            return
    except ModuleNotFoundError:
        # This could fail due to missing configuration values or
        # invalid module paths. Either way, no need to continue
        # if it fails.
        logger.error("Could not import module (keyval_storage_gateway).")
        return

    provider_class = _get_provider_class(
        interface=IKeyValStorageGateway,
        module_name=config["mugen"]["modules"]["core"]["gateway"]["storage"]["keyval"],
        provider_name="keyval_storage_gateway",
        logger=logger,
    )
    if provider_class is None:
        return

    injector.keyval_storage_gateway = provider_class(
        config=injector.config,
        logging_gateway=injector.logging_gateway,
    )


def _build_relational_storage_gateway_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """Build relational database storage gateway provider for DI container."""
    # Get logger.
    try:
        logger = injector.logging_gateway
    except AttributeError:
        # We'll get an AttributeError if injector
        # is incorrectly typed.
        logging.getLogger().error("Invalid injector (relational_storage_gateway).")
        return

    if logger is None:
        logger = logging.getLogger()
        logger.warning("Using root logger (relational_storage_gateway).")

    try:
        try:
            import_module(
                name=config["mugen"]["modules"]["core"]["gateway"]["storage"][
                    "relational"
                ]
            )
        except KeyError:
            logger.error("Invalid configuration (relational_storage_gateway).")
            return
    except ModuleNotFoundError:
        # This could fail due to missing configuration values or
        # invalid module paths. Either way, no need to continue
        # if it fails.
        logger.error("Could not import module (relational_storage_gateway).")
        return

    provider_class = _get_provider_class(
        interface=IRelationalStorageGateway,
        module_name=config["mugen"]["modules"]["core"]["gateway"]["storage"][
            "relational"
        ],
        provider_name="relational_storage_gateway",
        logger=logger,
    )
    if provider_class is None:
        return

    injector.relational_storage_gateway = provider_class(
        config=injector.config,
        logging_gateway=injector.logging_gateway,
    )


def _build_nlp_service_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """Build NLP service provider for DI container."""
    # Get logger.
    try:
        logger = injector.logging_gateway
    except AttributeError:
        # We'll get an AttributeError if injector
        # is incorrectly typed.
        logging.getLogger().error("Invalid injector (nlp_service).")
        return

    if logger is None:
        logger = logging.getLogger()
        logger.warning("Using root logger (nlp_service).")

    try:
        try:
            import_module(name=config["mugen"]["modules"]["core"]["service"]["nlp"])
        except KeyError:
            logger.error("Invalid configuration (nlp_service).")
            return
    except ModuleNotFoundError:
        # This could fail due to missing configuration values or
        # invalid module paths. Either way, no need to continue
        # if it fails.
        logger.error("Could not import module (nlp_service).")
        return

    provider_class = _get_provider_class(
        interface=INLPService,
        module_name=config["mugen"]["modules"]["core"]["service"]["nlp"],
        provider_name="nlp_service",
        logger=logger,
    )
    if provider_class is None:
        return

    injector.nlp_service = provider_class(
        logging_gateway=injector.logging_gateway,
    )


def _build_platform_service_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """Build platform service provider for DI container."""
    # Get logger.
    try:
        logger = injector.logging_gateway
    except AttributeError:
        # We'll get an AttributeError if injector
        # is incorrectly typed.
        logging.getLogger().error("Invalid injector (platform_service).")
        return

    if logger is None:
        logger = logging.getLogger()
        logger.warning("Using root logger (platform_service).")

    try:
        try:
            import_module(
                name=config["mugen"]["modules"]["core"]["service"]["platform"]
            )
        except KeyError:
            logger.error("Invalid configuration (platform_service).")
            return
    except ModuleNotFoundError:
        # This could fail due to missing configuration values or
        # invalid module paths. Either way, no need to continue
        # if it fails.
        logger.error("Could not import module (platform_service).")
        return

    provider_class = _get_provider_class(
        interface=IPlatformService,
        module_name=config["mugen"]["modules"]["core"]["service"]["platform"],
        provider_name="platform_service",
        logger=logger,
    )
    if provider_class is None:
        return

    injector.platform_service = provider_class(
        config=injector.config,
        logging_gateway=injector.logging_gateway,
    )


def _build_user_service_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """Build user service provider for DI container."""
    # Get logger.
    try:
        logger = injector.logging_gateway
    except AttributeError:
        # We'll get an AttributeError if injector
        # is incorrectly typed.
        logging.getLogger().error("Invalid injector (user_service).")
        return

    if logger is None:
        logger = logging.getLogger()
        logger.warning("Using root logger (user_service).")

    try:
        try:
            import_module(name=config["mugen"]["modules"]["core"]["service"]["user"])
        except KeyError:
            logger.error("Invalid configuration (user_service).")
            return
    except ModuleNotFoundError:
        # This could fail due to missing configuration values or
        # invalid module paths. Either way, no need to continue
        # if it fails.
        logger.error("Could not import module (user_service).")
        return

    provider_class = _get_provider_class(
        interface=IUserService,
        module_name=config["mugen"]["modules"]["core"]["service"]["user"],
        provider_name="user_service",
        logger=logger,
    )
    if provider_class is None:
        return

    injector.user_service = provider_class(
        keyval_storage_gateway=injector.keyval_storage_gateway,
        logging_gateway=injector.logging_gateway,
    )


def _build_messaging_service_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """Build messaging service provider for DI container."""
    # Get logger.
    try:
        logger = injector.logging_gateway
    except AttributeError:
        # We'll get an AttributeError if injector
        # is incorrectly typed.
        logging.getLogger().error("Invalid injector (messaging_service).")
        return

    if logger is None:
        logger = logging.getLogger()
        logger.warning("Using root logger (messaging_service).")

    try:
        try:
            import_module(
                name=config["mugen"]["modules"]["core"]["service"]["messaging"]
            )
        except KeyError:
            logger.error("Invalid configuration (messaging_service).")
            return
    except ModuleNotFoundError:
        # This could fail due to missing configuration values or
        # invalid module paths. Either way, no need to continue
        # if it fails.
        logger.error("Could not import module (messaging_service).")
        return

    provider_class = _get_provider_class(
        interface=IMessagingService,
        module_name=config["mugen"]["modules"]["core"]["service"]["messaging"],
        provider_name="messaging_service",
        logger=logger,
    )
    if provider_class is None:
        return

    injector.messaging_service = provider_class(
        config=injector.config,
        completion_gateway=injector.completion_gateway,
        keyval_storage_gateway=injector.keyval_storage_gateway,
        logging_gateway=injector.logging_gateway,
        user_service=injector.user_service,
    )


def _build_knowledge_gateway_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """Build knowledge gateway provider for DI container."""
    # Get logger.
    try:
        logger = injector.logging_gateway
    except AttributeError:
        # We'll get an AttributeError if injector
        # is incorrectly typed.
        logging.getLogger().error("Invalid injector (knowledge_gateway).")
        return

    if logger is None:
        logger = logging.getLogger()
        logger.warning("Using root logger (knowledge_gateway).")

    try:
        try:
            import_module(
                name=config["mugen"]["modules"]["core"]["gateway"]["knowledge"]
            )
        except (KeyError, ValueError):
            logger.error("Invalid configuration (knowledge_gateway).")
            return
    except ModuleNotFoundError:
        # This could fail due to missing configuration values or
        # invalid module paths. Either way, no need to continue
        # if it fails.
        logger.error("Could not import module (knowledge_gateway).")
        return

    provider_class = _get_provider_class(
        interface=IKnowledgeGateway,
        module_name=config["mugen"]["modules"]["core"]["gateway"]["knowledge"],
        provider_name="knowledge_gateway",
        logger=logger,
    )
    if provider_class is None:
        return

    injector.knowledge_gateway = provider_class(
        config=injector.config,
        logging_gateway=injector.logging_gateway,
    )


def _build_matrix_client_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """Build Matrix platform client provider for DI container."""
    # Get logger.
    try:
        logger = injector.logging_gateway
    except AttributeError:
        # We'll get an AttributeError if injector
        # is incorrectly typed.
        logging.getLogger().error("Invalid injector (matrix_client).")
        return

    if logger is None:
        logger = logging.getLogger()
        logger.warning("Using root logger (matrix_client).")

    # Don't load the client if the platform is not enabled.
    if "matrix" not in config["mugen"]["platforms"]:
        logger.warning("Matrix platform not active. Client not loaded.")
        return

    # Attempt to import the client module.

    try:
        try:
            import_module(name=config["mugen"]["modules"]["core"]["client"]["matrix"])
        except (KeyError, ValueError):
            logger.error("Invalid configuration (matrix_client).")
            return
    except ModuleNotFoundError:
        # This could fail due to missing configuration values or
        # invalid module paths. Either way, no need to continue
        # if it fails.
        logger.error("Could not import module (matrix_client).")
        return

    provider_class = _get_provider_class(
        interface=IMatrixClient,
        module_name=config["mugen"]["modules"]["core"]["client"]["matrix"],
        provider_name="matrix_client",
        logger=logger,
    )
    if provider_class is None:
        return

    injector.matrix_client = provider_class(
        config=injector.config,
        ipc_service=injector.ipc_service,
        keyval_storage_gateway=injector.keyval_storage_gateway,
        logging_gateway=injector.logging_gateway,
        messaging_service=injector.messaging_service,
        user_service=injector.user_service,
    )


def _build_telnet_client_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """Build telnet platform client provider for DI container."""
    # Get logger.
    try:
        logger = injector.logging_gateway
    except AttributeError:
        # We'll get an AttributeError if injector
        # is incorrectly typed.
        logging.getLogger().error("Invalid injector (telnet_client).")
        return

    if logger is None:
        logger = logging.getLogger()
        logger.warning("Using root logger (telnet_client).")

    # Don't load the client if the platform is not enabled.
    if "telnet" not in config["mugen"]["platforms"]:
        logger.warning("Telnet platform not active. Client not loaded.")
        return

    # Attempt to import the client module.
    try:
        try:
            import_module(name=config["mugen"]["modules"]["core"]["client"]["telnet"])
        except (KeyError, ValueError):
            logger.error("Invalid configuration (telnet_client).")
            return
    except ModuleNotFoundError:
        # This could fail due to missing configuration values or
        # invalid module paths. Either way, no need to continue
        # if it fails.
        logger.error("Could not import module (telnet_client).")
        return

    provider_class = _get_provider_class(
        interface=ITelnetClient,
        module_name=config["mugen"]["modules"]["core"]["client"]["telnet"],
        provider_name="telnet_client",
        logger=logger,
    )
    if provider_class is None:
        return

    injector.telnet_client = provider_class(
        config=injector.config,
        ipc_service=injector.ipc_service,
        keyval_storage_gateway=injector.keyval_storage_gateway,
        logging_gateway=injector.logging_gateway,
        messaging_service=injector.messaging_service,
        user_service=injector.user_service,
    )


def _build_whatsapp_client_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """Build WhatsApp platform client provider for DI container."""
    # Get logger.
    try:
        logger = injector.logging_gateway
    except AttributeError:
        # We'll get an AttributeError if injector
        # is incorrectly typed.
        logging.getLogger().error("Invalid injector (whatsapp_client).")
        return

    if logger is None:
        logger = logging.getLogger()
        logger.warning("Using root logger (whatsapp_client).")

    # Don't load the client if the platform is not enabled.
    if "whatsapp" not in config["mugen"]["platforms"]:
        logger.warning("WhatsApp platform not active. Client not loaded.")
        return

    # Attempt to import the client module.
    try:
        try:
            import_module(name=config["mugen"]["modules"]["core"]["client"]["whatsapp"])
        except (KeyError, ValueError):
            logger.error("Invalid configuration (whatsapp_client).")
            return
    except ModuleNotFoundError:
        # This could fail due to missing configuration values or
        # invalid module paths. Either way, no need to continue
        # if it fails.
        logger.error("Could not import module (whatsapp_client).")
        return

    provider_class = _get_provider_class(
        interface=IWhatsAppClient,
        module_name=config["mugen"]["modules"]["core"]["client"]["whatsapp"],
        provider_name="whatsapp_client",
        logger=logger,
    )
    if provider_class is None:
        return

    injector.whatsapp_client = provider_class(
        config=injector.config,
        ipc_service=injector.ipc_service,
        keyval_storage_gateway=injector.keyval_storage_gateway,
        logging_gateway=injector.logging_gateway,
        messaging_service=injector.messaging_service,
        user_service=injector.user_service,
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

    _build_logging_gateway_provider(config, injector)

    _build_completion_gateway_provider(config, injector)

    _build_ipc_service_provider(config, injector)

    _build_keyval_storage_gateway_provider(config, injector)

    _build_relational_storage_gateway_provider(config, injector)

    _build_nlp_service_provider(config, injector)

    _build_platform_service_provider(config, injector)

    _build_user_service_provider(config, injector)

    _build_messaging_service_provider(config, injector)

    _build_knowledge_gateway_provider(config, injector)

    _build_matrix_client_provider(config, injector)

    _build_telnet_client_provider(config, injector)

    _build_whatsapp_client_provider(config, injector)

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

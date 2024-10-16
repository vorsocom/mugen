"""Provides an application-wide dependency injection container."""

__all__ = ["container"]

from importlib import import_module
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


def _build_logging_gateway_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """"""
    import_module(name=config["mugen"]["modules"]["core"]["gateway"]["logging"])

    injector.logging_gateway = ILoggingGateway.__subclasses__()[0](
        config=injector.config,
    )


def _build_completion_gateway_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """"""
    import_module(name=config["mugen"]["modules"]["core"]["gateway"]["completion"])

    injector.completion_gateway = ICompletionGateway.__subclasses__()[0](
        config=injector.config,
        logging_gateway=injector.logging_gateway,
    )


def _build_ipc_service_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """"""
    import_module(name=config["mugen"]["modules"]["core"]["service"]["ipc"])

    injector.ipc_service = IIPCService.__subclasses__()[0](
        logging_gateway=injector.logging_gateway,
    )


def _build_keyval_storage_gateway_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """"""
    import_module(
        name=config["mugen"]["modules"]["core"]["gateway"]["storage"]["keyval"]
    )

    injector.keyval_storage_gateway = IKeyValStorageGateway.__subclasses__()[0](
        config=injector.config,
        logging_gateway=injector.logging_gateway,
    )


def _build_nlp_service_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """"""
    import_module(name=config["mugen"]["modules"]["core"]["service"]["nlp"])

    injector.nlp_service = INLPService.__subclasses__()[0](
        logging_gateway=injector.logging_gateway,
    )


def _build_platform_service_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """"""
    import_module(name=config["mugen"]["modules"]["core"]["service"]["platform"])

    injector.platform_service = IPlatformService.__subclasses__()[0](
        config=injector.config,
        logging_gateway=injector.logging_gateway,
    )


def _build_user_service_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """"""
    import_module(name=config["mugen"]["modules"]["core"]["service"]["user"])

    injector.user_service = IUserService.__subclasses__()[0](
        keyval_storage_gateway=injector.keyval_storage_gateway,
        logging_gateway=injector.logging_gateway,
    )


def _build_messaging_service_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """"""
    import_module(name=config["mugen"]["modules"]["core"]["service"]["messaging"])

    injector.messaging_service = IMessagingService.__subclasses__()[0](
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
    """"""
    try:
        import_module(name=config["mugen"]["modules"]["core"]["gateway"]["knowledge"])
    except KeyError:
        return

    injector.knowledge_gateway = IKnowledgeGateway.__subclasses__()[0](
        config=injector.config,
        logging_gateway=injector.logging_gateway,
        nlp_service=injector.nlp_service,
    )


def _build_matrix_client_provider(
    config: dict,
    injector: DependencyInjector,
) -> None:
    """"""
    # Don't load the client if the platform is not enabled.
    if "matrix" not in config["mugen"]["platforms"]:
        return

    # Attempt to import the client module.
    try:
        import_module(name=config["mugen"]["modules"]["core"]["client"]["matrix"])
    except ModuleNotFoundError:
        # Exit if the client module could not be imported.
        return

    injector.matrix_client = IMatrixClient.__subclasses__()[0](
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
    """"""
    # Don't load the client if the platform is not enabled.
    if "telnet" not in config["mugen"]["platforms"]:
        return

    # Attempt to import the client module.
    try:
        import_module(name=config["mugen"]["modules"]["core"]["client"]["telnet"])
    except ModuleNotFoundError:
        # Exit if the client module could not be imported.
        return

    injector.telnet_client = ITelnetClient.__subclasses__()[0](
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
    """"""
    # Don't load the client if the platform is not enabled.
    if "whatsapp" not in config["mugen"]["platforms"]:
        return

    # Attempt to import the client module.
    try:
        import_module(name=config["mugen"]["modules"]["core"]["client"]["whatsapp"])
    except ModuleNotFoundError:
        # Exit if the client module could not be imported.
        return

    injector.whatsapp_client = IWhatsAppClient.__subclasses__()[0](
        config=injector.config,
        ipc_service=injector.ipc_service,
        keyval_storage_gateway=injector.keyval_storage_gateway,
        logging_gateway=injector.logging_gateway,
        messaging_service=injector.messaging_service,
        user_service=injector.user_service,
    )


def _load_config(config_file: str) -> dict:
    """Load TOML configuration."""
    rel = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "..")
    basedir = os.path.realpath(rel)
    try:
        with open(os.path.join(basedir, config_file), "r", encoding="utf8") as f:
            config = tomlkit.loads(f.read()).value
            config["basedir"] = basedir
            return config
    except FileNotFoundError:
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

    _build_nlp_service_provider(config, injector)

    _build_platform_service_provider(config, injector)

    _build_user_service_provider(config, injector)

    _build_messaging_service_provider(config, injector)

    _build_knowledge_gateway_provider(config, injector)

    _build_matrix_client_provider(config, injector)

    _build_telnet_client_provider(config, injector)

    _build_whatsapp_client_provider(config, injector)

    return injector


container = _build_container()

"""Provides a dependency injection container."""

__all__ = ["DIContainer"]

import asyncio
from importlib import import_module
import os

from dependency_injector import containers, providers
from nio import AsyncClient
import tomlkit

from mugen.core.contract.client.whatsapp import IWhatsAppClient
from mugen.core.contract.gateway.completion import ICompletionGateway
from mugen.core.contract.gateway.knowledge import IKnowledgeRetrievalGateway
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.nlp import INLPService
from mugen.core.contract.service.user import IUserService


config: dict
with open(
    os.path.join(
        os.path.dirname(os.path.realpath(__file__)), "..", "..", "..", "mugen.toml"
    ),
    "r",
    encoding="utf8",
) as f:
    config = tomlkit.loads(f.read()).value

core = config["mugen"]["modules"]["core"]

import_module(name=core["gateway"]["logging"])
logging_gateway_class = ILoggingGateway.__subclasses__()[0]

import_module(name=core["gateway"]["completion"])
completion_gateway_class = ICompletionGateway.__subclasses__()[0]

import_module(name=core["service"]["ipc"])
ipc_service_class = IIPCService.__subclasses__()[0]

import_module(name=core["gateway"]["storage"]["keyval"])
storage_gateway_class = IKeyValStorageGateway.__subclasses__()[0]

import_module(name=core["service"]["nlp"])
nlp_service_class = INLPService.__subclasses__()[0]

import_module(name=core["service"]["user"])
user_service_class = IUserService.__subclasses__()[0]

import_module(name=core["service"]["messaging"])
messaging_service_class = IMessagingService.__subclasses__()[0]

# pylint: disable=invalid-name

knowledge_gateway_class = None
if "knowledge" in core["gateway"].keys() and core["gateway"]["knowledge"] != "":
    import_module(name=core["gateway"]["knowledge"])
    knowledge_gateway_class = IKnowledgeRetrievalGateway.__subclasses__()[0]

matrix_client_class = None
matrix_ipc_queue = None
if (
    "matrix" in core["client"].keys()
    and core["client"]["matrix"] != ""
    and "matrix" in config["mugen"]["platforms"]
):
    import_module(name=core["client"]["matrix"])
    matrix_client_class = AsyncClient.__subclasses__()[0]
    matrix_ipc_queue = asyncio.Queue()

whatsapp_client_class = None
whatsapp_ipc_queue = None
if (
    "whatsapp" in core["client"].keys()
    and core["client"]["whatsapp"] != ""
    and "whatsapp" in config["mugen"]["platforms"]
):
    import_module(name=core["client"]["whatsapp"])
    whatsapp_client_class = IWhatsAppClient.__subclasses__()[0]
    whatsapp_ipc_queue = asyncio.Queue()


# pylint: disable=c-extension-no-member
# pylint: disable=too-few-public-methods
class DIContainer(containers.DeclarativeContainer):
    """An application-wide dependency injector container."""

    config = providers.Configuration()

    logging_gateway = providers.Singleton(
        logging_gateway_class,
        config=config.delegate(),
    )

    completion_gateway = providers.Singleton(
        completion_gateway_class,
        config=config.delegate(),
        logging_gateway=logging_gateway,
    )

    ipc_service = providers.Singleton(
        ipc_service_class,
        logging_gateway=logging_gateway,
    )

    keyval_storage_gateway = providers.Singleton(
        storage_gateway_class,
        config=config.delegate(),
        logging_gateway=logging_gateway,
    )

    nlp_service = providers.Singleton(
        nlp_service_class,
        logging_gateway=logging_gateway,
    )

    user_service = providers.Singleton(
        user_service_class,
        keyval_storage_gateway=keyval_storage_gateway,
        logging_gateway=logging_gateway,
    )

    messaging_service = providers.Singleton(
        messaging_service_class,
        config=config.delegate(),
        completion_gateway=completion_gateway,
        keyval_storage_gateway=keyval_storage_gateway,
        logging_gateway=logging_gateway,
        user_service=user_service,
    )

    if knowledge_gateway_class:
        knowledge_gateway = providers.Singleton(
            knowledge_gateway_class,
            config=config.delegate(),
            logging_gateway=logging_gateway,
            nlp_service=nlp_service,
        )
    else:
        knowledge_gateway = providers.Object(None)

    if matrix_client_class:
        matrix_ipc_queue = providers.Object(matrix_ipc_queue)
        matrix_client = providers.Singleton(
            matrix_client_class,
            config=config.delegate(),
            ipc_queue=matrix_ipc_queue,
            ipc_service=ipc_service,
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=logging_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
        )
    else:
        matrix_client = providers.Object(None)
        matrix_ipc_queue = providers.Object(None)

    if whatsapp_client_class:
        whatsapp_ipc_queue = providers.Object(whatsapp_ipc_queue)
        whatsapp_client = providers.Singleton(
            whatsapp_client_class,
            config=config.delegate(),
            ipc_queue=whatsapp_ipc_queue,
            ipc_service=ipc_service,
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=logging_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
        )
    else:
        whatsapp_client = providers.Object(None)
        whatsapp_ipc_queue = providers.Object(None)

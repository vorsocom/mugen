"""Provides a dependency injection container."""

__all__ = ["DIContainer"]

import asyncio
from importlib import import_module
import os
import json
from types import SimpleNamespace

from dependency_injector import containers, providers
from nio import AsyncClient

from mugen.core.contract.completion_gateway import ICompletionGateway
from mugen.core.contract.ipc_service import IIPCService
from mugen.core.contract.keyval_storage_gateway import IKeyValStorageGateway
from mugen.core.contract.knowledge_retrieval_gateway import IKnowledgeRetrievalGateway
from mugen.core.contract.logging_gateway import ILoggingGateway
from mugen.core.contract.messaging_service import IMessagingService
from mugen.core.contract.nlp_service import INLPService
from mugen.core.contract.user_service import IUserService
from mugen.core.contract.whatsapp_client import IWhatsAppClient

default_modules = SimpleNamespace(**json.loads(os.getenv("MUGEN_DEFAULT_MODULES")))
platforms = json.loads(os.getenv("MUGEN_PLATFORMS"))

import_module(name=default_modules.logging_gateway)
logging_gateway_class = ILoggingGateway.__subclasses__()[0]

import_module(name=default_modules.completion_gateway)
completion_gateway_class = ICompletionGateway.__subclasses__()[0]

import_module(name=default_modules.ipc_service)
ipc_service_class = IIPCService.__subclasses__()[0]

import_module(name=default_modules.storage_gateway)
storage_gateway_class = IKeyValStorageGateway.__subclasses__()[0]

import_module(name=default_modules.nlp_service)
nlp_service_class = INLPService.__subclasses__()[0]

import_module(name=default_modules.user_service)
user_service_class = IUserService.__subclasses__()[0]

import_module(name=default_modules.messaging_service)
messaging_service_class = IMessagingService.__subclasses__()[0]

# pylint: disable=invalid-name

knowledge_retrieval_class = None
if (
    hasattr(default_modules, "knowledge_retrieval")
    and default_modules.knowledge_retrieval != ""
):
    import_module(name=default_modules.knowledge_retrieval)
    knowledge_retrieval_class = IKnowledgeRetrievalGateway.__subclasses__()[0]

matrix_client_class = None
matrix_ipc_queue = None
if (
    hasattr(default_modules, "matrix_client")
    and default_modules.matrix_client != ""
    and "matrix" in platforms
):
    import_module(name=default_modules.matrix_client)
    matrix_client_class = AsyncClient.__subclasses__()[0]
    matrix_ipc_queue = asyncio.Queue()

whatsapp_client_class = None
whatsapp_ipc_queue = None
if (
    hasattr(default_modules, "whatsapp_client")
    and default_modules.whatsapp_client != ""
    and "whatsapp" in platforms
):
    import_module(name=default_modules.whatsapp_client)
    whatsapp_client_class = IWhatsAppClient.__subclasses__()[0]
    whatsapp_ipc_queue = asyncio.Queue()


# pylint: disable=c-extension-no-member
# pylint: disable=too-few-public-methods
class DIContainer(containers.DeclarativeContainer):
    """An application-wide dependency injector container."""

    config = providers.Configuration()

    logging_gateway = providers.Singleton(
        logging_gateway_class,
        config=config,
    )

    completion_gateway = providers.Singleton(
        completion_gateway_class,
        config=config,
        logging_gateway=logging_gateway,
    )

    ipc_service = providers.Singleton(
        ipc_service_class,
        config=config,
        logging_gateway=logging_gateway,
    )

    keyval_storage_gateway = providers.Singleton(
        storage_gateway_class,
        config=config,
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
        config=config,
        completion_gateway=completion_gateway,
        keyval_storage_gateway=keyval_storage_gateway,
        logging_gateway=logging_gateway,
        user_service=user_service,
    )

    if knowledge_retrieval_class:
        knowledge_retrieval_gateway = providers.Singleton(
            knowledge_retrieval_class,
            config=config,
            logging_gateway=logging_gateway,
            nlp_service=nlp_service,
        )
    else:
        knowledge_retrieval_gateway = providers.Object(None)

    if matrix_client_class:
        matrix_ipc_queue = providers.Object(matrix_ipc_queue)
        matrix_client = providers.Singleton(
            matrix_client_class,
            di_config=config,
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
            config=config,
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

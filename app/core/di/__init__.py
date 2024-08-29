"""Provides a dependency injection container."""

__all__ = ["DIContainer"]

import asyncio
from importlib import import_module
import os
import json
from types import SimpleNamespace

from dependency_injector import containers, providers
from nio import AsyncClient

from app.core.contract.completion_gateway import ICompletionGateway
from app.core.contract.ipc_service import IIPCService
from app.core.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.core.contract.knowledge_retrieval_gateway import IKnowledgeRetrievalGateway
from app.core.contract.logging_gateway import ILoggingGateway
from app.core.contract.messaging_service import IMessagingService
from app.core.contract.nlp_service import INLPService
from app.core.contract.user_service import IUserService

default_modules = SimpleNamespace(**json.loads(os.getenv("GLORIA_DEFAULT_MODULES")))

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

import_module(name=default_modules.knowledge_retrieval)
knowledge_retrieval_class = IKnowledgeRetrievalGateway.__subclasses__()[0]

import_module(name=default_modules.user_service)
user_service_class = IUserService.__subclasses__()[0]

import_module(name=default_modules.messaging_service)
messaging_service_class = IMessagingService.__subclasses__()[0]

import_module(name=default_modules.client)
client_class = AsyncClient.__subclasses__()[0]

ipc_queue = asyncio.Queue()


# pylint: disable=c-extension-no-member
# pylint: disable=too-few-public-methods
class DIContainer(containers.DeclarativeContainer):
    """An application-wide dependency injector container."""

    config = providers.Configuration()

    ipc_queue = providers.Object(ipc_queue)

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

    knowledge_retrieval_gateway = providers.Singleton(
        knowledge_retrieval_class,
        config=config,
        logging_gateway=logging_gateway,
        nlp_service=nlp_service,
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

    client = providers.Singleton(
        client_class,
        di_config=config,
        ipc_queue=ipc_queue,
        ipc_service=ipc_service,
        keyval_storage_gateway=keyval_storage_gateway,
        logging_gateway=logging_gateway,
        messaging_service=messaging_service,
        user_service=user_service,
    )

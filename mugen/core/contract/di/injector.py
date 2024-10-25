"""Provides helper class for dependency injection containers."""

__all__ = ["IDependencyInjector"]

from abc import ABC, abstractmethod
from types import SimpleNamespace

from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.client.telnet import ITelnetClient
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


class IDependencyInjector(ABC):
    """An helper for dependency injection containers."""

    @property
    @abstractmethod
    def config(self) -> SimpleNamespace:
        """Get the global configuration variable."""

    @property
    @abstractmethod
    def logging_gateway(self) -> ILoggingGateway:
        """Get the global logging gateway."""

    @property
    @abstractmethod
    def completion_gateway(self) -> ICompletionGateway:
        """Get the global completion gateway."""

    @property
    @abstractmethod
    def ipc_service(self) -> IIPCService:
        """Get the global IPC service."""

    @property
    @abstractmethod
    def keyval_storage_gateway(self) -> IKeyValStorageGateway:
        """Get the global key-value storage gateway."""

    @property
    @abstractmethod
    def nlp_service(self) -> INLPService:
        """Get the global NLP service."""

    @property
    @abstractmethod
    def platform_service(self) -> IPlatformService:
        """Get the global platform service."""

    @property
    @abstractmethod
    def user_service(self) -> IUserService:
        """Get the global user service."""

    @property
    @abstractmethod
    def messaging_service(self) -> IMessagingService:
        """Get the global messaging service."""

    @property
    @abstractmethod
    def knowledge_gateway(self) -> IKnowledgeGateway:
        """Get the global knowledge retrieval gateway."""

    @property
    @abstractmethod
    def matrix_client(self) -> IMatrixClient:
        """Get the global Matrix client."""

    @property
    @abstractmethod
    def telnet_client(self) -> ITelnetClient:
        """Get the global telnet client."""

    @property
    @abstractmethod
    def whatsapp_client(self) -> IWhatsAppClient:
        """Get the global WhatsApp client."""

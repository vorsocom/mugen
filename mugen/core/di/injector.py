"""Provides an implementation of IDIContainer."""

__all__ = ["DependencyInjector"]

from types import MappingProxyType, SimpleNamespace
from typing import Any, Mapping

from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.client.telnet import ITelnetClient
from mugen.core.contract.client.whatsapp import IWhatsAppClient
from mugen.core.contract.di.injector import IDependencyInjector
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


# pylint: disable=too-many-instance-attributes
class DependencyInjector(IDependencyInjector):
    """An implementation of IDIContainer."""

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def __init__(
        self,
        config: SimpleNamespace = None,
        logging_gateway: ILoggingGateway = None,
        completion_gateway: ICompletionGateway = None,
        ipc_service: IIPCService = None,
        keyval_storage_gateway: IKeyValStorageGateway = None,
        relational_storage_gateway: IRelationalStorageGateway = None,
        nlp_service: INLPService = None,
        platform_service: IPlatformService = None,
        user_service: IUserService = None,
        messaging_service: IMessagingService = None,
        knowledge_gateway: IKnowledgeGateway = None,
        matrix_client: IMatrixClient = None,
        telnet_client: ITelnetClient = None,
        whatsapp_client: IWhatsAppClient = None,
    ):
        self.__config = config
        self.__logging_gateway = logging_gateway
        self.__completion_gateway = completion_gateway
        self.__ipc_service = ipc_service
        self.__keyval_storage_gateway = keyval_storage_gateway
        self.__relational_storage_gateway = relational_storage_gateway
        self.__nlp_service = nlp_service
        self.__platform_service = platform_service
        self.__user_service = user_service
        self.__messaging_service = messaging_service
        self.__knowledge_gateway = knowledge_gateway
        self.__matrix_client = matrix_client
        self.__telnet_client = telnet_client
        self.__whatsapp_client = whatsapp_client

        self.__ext_services: dict[str, Any] = {}

    @property
    def config(self) -> SimpleNamespace:
        return self.__config

    @config.setter
    def config(self, value: SimpleNamespace):
        self.__config = value

    @property
    def logging_gateway(self) -> ILoggingGateway:
        return self.__logging_gateway

    @logging_gateway.setter
    def logging_gateway(self, value: ILoggingGateway) -> None:
        self.__logging_gateway = value

    @property
    def completion_gateway(self) -> ICompletionGateway:
        return self.__completion_gateway

    @completion_gateway.setter
    def completion_gateway(self, value: ICompletionGateway) -> None:
        self.__completion_gateway = value

    @property
    def ipc_service(self) -> IIPCService:
        return self.__ipc_service

    @ipc_service.setter
    def ipc_service(self, value: IIPCService) -> None:
        self.__ipc_service = value

    @property
    def keyval_storage_gateway(self) -> IKeyValStorageGateway:
        return self.__keyval_storage_gateway

    @keyval_storage_gateway.setter
    def keyval_storage_gateway(self, value: IKeyValStorageGateway) -> None:
        self.__keyval_storage_gateway = value

    @property
    def relational_storage_gateway(self) -> IRelationalStorageGateway:
        return self.__relational_storage_gateway

    @relational_storage_gateway.setter
    def relational_storage_gateway(self, value: IRelationalStorageGateway) -> None:
        self.__relational_storage_gateway = value

    @property
    def nlp_service(self) -> INLPService:
        return self.__nlp_service

    @nlp_service.setter
    def nlp_service(self, value: INLPService) -> None:
        self.__nlp_service = value

    @property
    def platform_service(self) -> IPlatformService:
        return self.__platform_service

    @platform_service.setter
    def platform_service(self, value: IPlatformService) -> None:
        self.__platform_service = value

    @property
    def user_service(self) -> IUserService:
        return self.__user_service

    @user_service.setter
    def user_service(self, value: IUserService) -> None:
        self.__user_service = value

    @property
    def messaging_service(self) -> IMessagingService:
        return self.__messaging_service

    @messaging_service.setter
    def messaging_service(self, value: IMessagingService) -> None:
        self.__messaging_service = value

    @property
    def knowledge_gateway(self) -> IKnowledgeGateway:
        return self.__knowledge_gateway

    @knowledge_gateway.setter
    def knowledge_gateway(self, value: IKnowledgeGateway) -> None:
        self.__knowledge_gateway = value

    @property
    def matrix_client(self) -> IMatrixClient:
        return self.__matrix_client

    @matrix_client.setter
    def matrix_client(self, value: IMatrixClient) -> None:
        self.__matrix_client = value

    @property
    def telnet_client(self) -> ITelnetClient:
        return self.__telnet_client

    @telnet_client.setter
    def telnet_client(self, value: ITelnetClient) -> None:
        self.__telnet_client = value

    @property
    def whatsapp_client(self) -> IWhatsAppClient:
        return self.__whatsapp_client

    @whatsapp_client.setter
    def whatsapp_client(self, value: IWhatsAppClient) -> None:
        self.__whatsapp_client = value

    @staticmethod
    def _normalise_ext_service_name(name: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Service name must be a non-empty string.")

        return name.strip()

    def register_ext_service(
        self, name: str, service: Any, *, override: bool = False
    ) -> None:
        name = self._normalise_ext_service_name(name)

        if not override and name in self.__ext_services:
            raise KeyError(f"Extension service '{name}' already registered.")

        self.__ext_services[name] = service

    def get_ext_service(self, name: str, default: Any | None = None) -> Any:
        name = self._normalise_ext_service_name(name)

        try:
            return self.__ext_services[name]
        except KeyError:
            if default is not None:
                return default
            raise KeyError(f"Extension service '{name}' not found.") from None

    def get_required_ext_service(self, name: str) -> Any:
        return self.get_ext_service(name)

    def has_ext_service(self, name: str) -> bool:
        name = self._normalise_ext_service_name(name)
        return name in self.__ext_services

    @property
    def ext_services(self) -> Mapping[str, Any]:
        # Expose a read-only view to avoid accidental mutation.
        return MappingProxyType(self.__ext_services)

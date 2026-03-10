"""Provides helper class for dependency injection containers."""

__all__ = ["IDependencyInjector"]

from abc import ABC, abstractmethod
from types import SimpleNamespace
from typing import Any, Mapping

from mugen.core.contract.client.line import ILineClient
from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.client.signal import ISignalClient
from mugen.core.contract.client.telegram import ITelegramClient
from mugen.core.contract.client.wechat import IWeChatClient
from mugen.core.contract.client.web import IWebClient
from mugen.core.contract.client.whatsapp import IWhatsAppClient
from mugen.core.contract.agent import (
    IAgentExecutor,
    IAgentRuntime,
    IEvaluationEngine,
    IPlanRunStore,
    IPlanningEngine,
)
from mugen.core.contract.context import IContextEngine
from mugen.core.contract.gateway.completion import ICompletionGateway
from mugen.core.contract.gateway.email import IEmailGateway
from mugen.core.contract.gateway.knowledge import IKnowledgeGateway
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.sms import ISMSGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.gateway.storage.media import IMediaStorageGateway
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.web_runtime import IWebRuntimeStore
from mugen.core.contract.service.ingress import IMessagingIngressService
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
    def email_gateway(self) -> IEmailGateway:
        """Get the global email gateway."""

    @property
    @abstractmethod
    def sms_gateway(self) -> ISMSGateway:
        """Get the global SMS gateway."""

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
    def media_storage_gateway(self) -> IMediaStorageGateway:
        """Get the global media storage gateway."""

    @property
    @abstractmethod
    def relational_storage_gateway(self) -> IRelationalStorageGateway:
        """Get the global relational database storage gateway."""

    @property
    @abstractmethod
    def relational_runtime(self) -> Any:
        """Get the shared relational runtime resources."""

    @property
    @abstractmethod
    def web_runtime_store(self) -> IWebRuntimeStore:
        """Get the global web-runtime storage gateway."""

    @property
    @abstractmethod
    def ingress_service(self) -> IMessagingIngressService:
        """Get the shared messaging ingress service."""

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
    def context_engine_service(self) -> IContextEngine:
        """Get the global context engine service."""

    @property
    @abstractmethod
    def planning_engine_service(self) -> IPlanningEngine | None:
        """Get the optional planning engine service."""

    @property
    @abstractmethod
    def evaluation_engine_service(self) -> IEvaluationEngine | None:
        """Get the optional evaluation engine service."""

    @property
    @abstractmethod
    def agent_executor_service(self) -> IAgentExecutor | None:
        """Get the optional agent executor service."""

    @property
    @abstractmethod
    def plan_run_store_service(self) -> IPlanRunStore | None:
        """Get the optional plan run store service."""

    @property
    @abstractmethod
    def agent_runtime_service(self) -> IAgentRuntime | None:
        """Get the optional agent runtime coordinator service."""

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
    def line_client(self) -> ILineClient:
        """Get the global LINE client."""

    @property
    @abstractmethod
    def signal_client(self) -> ISignalClient:
        """Get the global Signal client."""

    @property
    @abstractmethod
    def telegram_client(self) -> ITelegramClient:
        """Get the global Telegram client."""

    @property
    @abstractmethod
    def wechat_client(self) -> IWeChatClient:
        """Get the global WeChat client."""

    @property
    @abstractmethod
    def whatsapp_client(self) -> IWhatsAppClient:
        """Get the global WhatsApp client."""

    @property
    @abstractmethod
    def web_client(self) -> IWebClient:
        """Get the global Web client."""

    @abstractmethod
    def register_ext_service(
        self,
        name: str,
        service: Any,
        *,
        override: bool = False,
    ) -> None:
        """Register an extension-provided service under a given name."""

    @abstractmethod
    def register_ext_services(
        self,
        services: Mapping[str, Any],
        *,
        override: bool = False,
        atomic: bool = False,
    ) -> None:
        """Register multiple extension-provided services."""

    @abstractmethod
    def get_ext_service(self, name: str, default: Any = ...) -> Any:
        """Retrieve a previously registered extension service."""

    @abstractmethod
    def get_required_ext_service(self, name: str) -> Any:
        """Retrieve a previously registered extension service or raise."""

    @abstractmethod
    def has_ext_service(self, name: str) -> bool:
        """Check whether an extension service has been registered."""

    @property
    @abstractmethod
    def ext_services(self) -> Mapping[str, Any]:
        """Read-only view over all registered extension services."""

"""Provides runtime wiring for governed Knowledge Pack search projections."""

__all__ = ["KnowledgePackFWExtension"]

from quart import Quart

from mugen.core import di
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.contract.gateway.knowledge import IKnowledgeGateway
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms import IRelationalStorageGateway
from mugen.core.plugin.knowledge_pack.runtime import configure_knowledge_gateway
from mugen.core.plugin.knowledge_pack.service.projection_worker import (
    KnowledgeProjectionWorker,
)
from mugen.core.plugin.knowledge_pack.service.retrieval import (
    KnowledgeRetrievalService,
)


def _rsg_provider():
    return di.container.relational_storage_gateway


def _gateway_provider():
    return di.container.knowledge_gateway


def _logging_provider():
    return di.container.logging_gateway


class KnowledgePackFWExtension(IFWExtension):  # pylint: disable=too-few-public-methods
    """Register safe retrieval and the durable projection worker when configured."""

    def __init__(
        self,
        rsg_provider=_rsg_provider,
        gateway_provider=_gateway_provider,
        logging_provider=_logging_provider,
    ) -> None:
        self._rsg: IRelationalStorageGateway = rsg_provider()
        self._gateway: IKnowledgeGateway | None = gateway_provider()
        self._logging_gateway: ILoggingGateway = logging_provider()

    @property
    def platforms(self) -> list[str]:
        return []

    async def setup(self, app: Quart) -> None:
        configure_knowledge_gateway(self._gateway)
        if self._gateway is not None:
            retrieval = KnowledgeRetrievalService(
                rsg=self._rsg,
                gateway=self._gateway,
            )
            worker = KnowledgeProjectionWorker(
                rsg=self._rsg,
                gateway=self._gateway,
                logging_gateway=self._logging_gateway,
            )
            di.container.register_ext_services(
                {
                    di.EXT_SERVICE_KNOWLEDGE_RETRIEVAL: retrieval,
                    di.EXT_SERVICE_KNOWLEDGE_PROJECTION_WORKER: worker,
                },
                override=True,
            )
            app.add_background_task(worker.run)

        # Import endpoints after runtime services are available.
        # pylint: disable=import-outside-toplevel, unused-import
        import mugen.core.plugin.knowledge_pack.api  # noqa: F401

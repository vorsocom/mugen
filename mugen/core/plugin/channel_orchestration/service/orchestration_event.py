"""Provides a CRUD service for orchestration events."""

__all__ = ["OrchestrationEventService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from ..contract.service.orchestration_event import IOrchestrationEventService
from ..domain import OrchestrationEventDE


class OrchestrationEventService(  # pylint: disable=too-few-public-methods
    IRelationalService[OrchestrationEventDE],
    IOrchestrationEventService,
):
    """A CRUD service for orchestration events."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=OrchestrationEventDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

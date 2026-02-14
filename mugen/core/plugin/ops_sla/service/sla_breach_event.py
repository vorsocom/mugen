"""Provides a CRUD service for sla breach events."""

__all__ = ["SlaBreachEventService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_sla.contract.service.sla_breach_event import (
    ISlaBreachEventService,
)
from mugen.core.plugin.ops_sla.domain import SlaBreachEventDE


class SlaBreachEventService(  # pylint: disable=too-few-public-methods
    IRelationalService[SlaBreachEventDE],
    ISlaBreachEventService,
):
    """A CRUD service for append-only SLA breach events."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=SlaBreachEventDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

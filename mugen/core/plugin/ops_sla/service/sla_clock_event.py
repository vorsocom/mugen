"""Provides a CRUD service for SLA clock-event records."""

__all__ = ["SlaClockEventService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_sla.contract.service.sla_clock_event import (
    ISlaClockEventService,
)
from mugen.core.plugin.ops_sla.domain import SlaClockEventDE


class SlaClockEventService(  # pylint: disable=too-few-public-methods
    IRelationalService[SlaClockEventDE],
    ISlaClockEventService,
):
    """A CRUD service for append-only SLA clock events."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=SlaClockEventDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

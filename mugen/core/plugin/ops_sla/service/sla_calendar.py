"""Provides a CRUD service for sla calendars."""

__all__ = ["SlaCalendarService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_sla.contract.service.sla_calendar import ISlaCalendarService
from mugen.core.plugin.ops_sla.domain import SlaCalendarDE


class SlaCalendarService(  # pylint: disable=too-few-public-methods
    IRelationalService[SlaCalendarDE],
    ISlaCalendarService,
):
    """A CRUD service for SLA calendar definitions."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=SlaCalendarDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

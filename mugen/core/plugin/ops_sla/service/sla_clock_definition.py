"""Provides a CRUD service for SLA clock-definition records."""

__all__ = ["SlaClockDefinitionService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_sla.contract.service.sla_clock_definition import (
    ISlaClockDefinitionService,
)
from mugen.core.plugin.ops_sla.domain import SlaClockDefinitionDE


class SlaClockDefinitionService(  # pylint: disable=too-few-public-methods
    IRelationalService[SlaClockDefinitionDE],
    ISlaClockDefinitionService,
):
    """A CRUD service for SLA clock-definition rows."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=SlaClockDefinitionDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

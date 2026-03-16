"""Provides a CRUD service for sla targets."""

__all__ = ["SlaTargetService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_sla.contract.service.sla_target import ISlaTargetService
from mugen.core.plugin.ops_sla.domain import SlaTargetDE


class SlaTargetService(  # pylint: disable=too-few-public-methods
    IRelationalService[SlaTargetDE],
    ISlaTargetService,
):
    """A CRUD service for SLA target definitions."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=SlaTargetDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

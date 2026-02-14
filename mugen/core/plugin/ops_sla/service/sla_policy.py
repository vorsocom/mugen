"""Provides a CRUD service for sla policies."""

__all__ = ["SlaPolicyService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_sla.contract.service.sla_policy import ISlaPolicyService
from mugen.core.plugin.ops_sla.domain import SlaPolicyDE


class SlaPolicyService(  # pylint: disable=too-few-public-methods
    IRelationalService[SlaPolicyDE],
    ISlaPolicyService,
):
    """A CRUD service for SLA policy definitions."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=SlaPolicyDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

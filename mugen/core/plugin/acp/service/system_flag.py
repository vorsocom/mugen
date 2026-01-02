"""Provides a service for the SystemFlag declarative model."""

__all__ = ["SystemFlagService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.contract.service import ISystemFlagService
from mugen.core.plugin.acp.domain import SystemFlagDE


class SystemFlagService(
    IRelationalService[SystemFlagDE],
    ISystemFlagService,
):
    """A service for the SystemFlag declarative model."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=SystemFlagDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

"""Provides a service for the Tenant declarative model."""

__all__ = ["TenantService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.contract.service import IPersonService
from mugen.core.plugin.acp.domain import TenantDE


class TenantService(
    IRelationalService[TenantDE],
    IPersonService,
):
    """A service for the Tenant declarative model."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=TenantDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

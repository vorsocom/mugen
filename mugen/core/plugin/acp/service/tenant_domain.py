"""Provides a service for the TenantDomain declarative model."""

__all__ = ["TenantDomainService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.contract.service import ITenantDomainService
from mugen.core.plugin.acp.domain import TenantDomainDE


class TenantDomainService(
    IRelationalService[TenantDomainDE],
    ITenantDomainService,
):
    """A service for the Tenant declarative model."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=TenantDomainDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

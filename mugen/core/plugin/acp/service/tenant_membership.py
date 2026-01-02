"""Provides a service for the TenantMembership declarative model."""

__all__ = ["TenantMembershipService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.contract.service import IPersonService
from mugen.core.plugin.acp.domain import TenantMembershipDE


class TenantMembershipService(
    IRelationalService[TenantMembershipDE],
    IPersonService,
):
    """A service for the Tenant declarative model."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=TenantMembershipDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

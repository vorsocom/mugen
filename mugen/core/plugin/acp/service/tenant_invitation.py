"""Provides a service for the TenantInvitation declarative model."""

__all__ = ["TenantInvitationService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.contract.service import IPersonService
from mugen.core.plugin.acp.domain import TenantInvitationDE


class TenantInvitationService(
    IRelationalService[TenantInvitationDE],
    IPersonService,
):
    """A service for the Tenant declarative model."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=TenantInvitationDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

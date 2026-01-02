"""Provides a service for the Role declarative model."""

__all__ = ["RoleService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.contract.service import IRoleService
from mugen.core.plugin.acp.domain import RoleDE


class RoleService(
    IRelationalService[RoleDE],
    IRoleService,
):
    """A service for the Role declarative model."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=RoleDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

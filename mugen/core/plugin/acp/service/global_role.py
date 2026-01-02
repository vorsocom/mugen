"""Provides a service for the GlobalRole declarative model."""

__all__ = ["GlobalRoleService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.contract.service import IGlobalRoleService
from mugen.core.plugin.acp.domain import GlobalRoleDE


class GlobalRoleService(
    IRelationalService[GlobalRoleDE],
    IGlobalRoleService,
):
    """A service for the GlobalRole declarative model."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=GlobalRoleDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

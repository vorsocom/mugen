"""Provides a service for the PermissionObject declarative model."""

__all__ = ["PermissionObjectService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.contract.service import IPermissionObjectService
from mugen.core.plugin.acp.domain import PermissionObjectDE


class PermissionObjectService(
    IRelationalService[PermissionObjectDE],
    IPermissionObjectService,
):
    """A service for the PermissionObject declarative model."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=PermissionObjectDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

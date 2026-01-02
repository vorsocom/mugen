"""Provides a service for the PermissionType declarative model."""

__all__ = ["PermissionTypeService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.contract.service import IPermissionTypeService
from mugen.core.plugin.acp.domain import PermissionTypeDE


class PermissionTypeService(
    IRelationalService[PermissionTypeDE],
    IPermissionTypeService,
):
    """A service for the PermissionType declarative model."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=PermissionTypeDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

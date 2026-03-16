"""Provides a service for the PermissionEntry declarative model."""

__all__ = ["PermissionEntryService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.contract.service import IPermissionEntryService
from mugen.core.plugin.acp.domain import PermissionEntryDE


class PermissionEntryService(
    IRelationalService[PermissionEntryDE],
    IPermissionEntryService,
):
    """A service for the PermissionEntry declarative model."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=PermissionEntryDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

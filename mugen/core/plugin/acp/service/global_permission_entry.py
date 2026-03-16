"""Provides a service for the GlobalPermissionEntry declarative model."""

__all__ = ["GlobalPermissionEntryService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.contract.service import IGlobalPermissionEntryService
from mugen.core.plugin.acp.domain import GlobalPermissionEntryDE


class GlobalPermissionEntryService(
    IRelationalService[GlobalPermissionEntryDE],
    IGlobalPermissionEntryService,
):
    """A service for the GlobalPermissionEntry declarative model."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=GlobalPermissionEntryDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

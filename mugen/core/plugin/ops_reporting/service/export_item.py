"""Provides a CRUD service for export item ledger rows."""

__all__ = ["ExportItemService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_reporting.contract.service.export_item import (
    IExportItemService,
)
from mugen.core.plugin.ops_reporting.domain import ExportItemDE


class ExportItemService(  # pylint: disable=too-few-public-methods
    IRelationalService[ExportItemDE],
    IExportItemService,
):
    """A CRUD service for read-only export item ledger entries."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=ExportItemDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

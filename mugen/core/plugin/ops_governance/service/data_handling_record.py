"""Provides a CRUD service for data handling records."""

__all__ = ["DataHandlingRecordService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_governance.contract.service.data_handling_record import (
    IDataHandlingRecordService,
)
from mugen.core.plugin.ops_governance.domain import DataHandlingRecordDE


class DataHandlingRecordService(  # pylint: disable=too-few-public-methods
    IRelationalService[DataHandlingRecordDE],
    IDataHandlingRecordService,
):
    """A CRUD service for data handling records."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=DataHandlingRecordDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

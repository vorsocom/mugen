"""Provides a CRUD service for meter definitions."""

__all__ = ["MeterDefinitionService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_metering.contract.service.meter_definition import (
    IMeterDefinitionService,
)
from mugen.core.plugin.ops_metering.domain import MeterDefinitionDE


class MeterDefinitionService(  # pylint: disable=too-few-public-methods
    IRelationalService[MeterDefinitionDE],
    IMeterDefinitionService,
):
    """A CRUD service for metering definition records."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=MeterDefinitionDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

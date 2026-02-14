"""Provides a CRUD service for rated usage records."""

__all__ = ["RatedUsageService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_metering.contract.service.rated_usage import (
    IRatedUsageService,
)
from mugen.core.plugin.ops_metering.domain import RatedUsageDE


class RatedUsageService(  # pylint: disable=too-few-public-methods
    IRelationalService[RatedUsageDE],
    IRatedUsageService,
):
    """A CRUD service for rated usage records."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=RatedUsageDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

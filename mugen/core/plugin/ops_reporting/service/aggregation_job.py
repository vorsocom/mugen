"""Provides a CRUD service for aggregation jobs."""

__all__ = ["AggregationJobService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_reporting.contract.service.aggregation_job import (
    IAggregationJobService,
)
from mugen.core.plugin.ops_reporting.domain import AggregationJobDE


class AggregationJobService(  # pylint: disable=too-few-public-methods
    IRelationalService[AggregationJobDE],
    IAggregationJobService,
):
    """A CRUD service for aggregation job metadata."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=AggregationJobDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

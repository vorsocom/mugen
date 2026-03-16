"""Provides a CRUD service for billing usage allocations."""

__all__ = ["UsageAllocationService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.billing.contract.service.usage_allocation import (
    IUsageAllocationService,
)
from mugen.core.plugin.billing.domain import UsageAllocationDE


class UsageAllocationService(  # pylint: disable=too-few-public-methods
    IRelationalService[UsageAllocationDE],
    IUsageAllocationService,
):
    """A CRUD service for billing usage allocations."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=UsageAllocationDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

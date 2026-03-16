"""Provides a CRUD service for billing usage events."""

__all__ = ["UsageEventService"]

from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway

from mugen.core.plugin.billing.contract.service.usage_event import IUsageEventService
from mugen.core.plugin.billing.domain import UsageEventDE


class UsageEventService(  # pylint: disable=too-few-public-methods
    IRelationalService[UsageEventDE],
    IUsageEventService,
):
    """A CRUD service for billing usage events."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=UsageEventDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

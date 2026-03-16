"""Provides a CRUD service for billing entitlement buckets."""

__all__ = ["EntitlementBucketService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.billing.contract.service.entitlement_bucket import (
    IEntitlementBucketService,
)
from mugen.core.plugin.billing.domain import EntitlementBucketDE


class EntitlementBucketService(  # pylint: disable=too-few-public-methods
    IRelationalService[EntitlementBucketDE],
    IEntitlementBucketService,
):
    """A CRUD service for billing entitlement buckets."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=EntitlementBucketDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

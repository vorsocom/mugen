"""Provides read-only access to entitlement adjustments."""

__all__ = ["EntitlementAdjustmentService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.billing.domain import EntitlementAdjustmentDE


class EntitlementAdjustmentService(IRelationalService[EntitlementAdjustmentDE]):
    """A read-only service for append-only entitlement adjustments."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=EntitlementAdjustmentDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

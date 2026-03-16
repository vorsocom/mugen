"""Provides a CRUD service for billing adjustments."""

__all__ = ["AdjustmentService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.billing.contract.service.adjustment import IAdjustmentService
from mugen.core.plugin.billing.domain import AdjustmentDE


class AdjustmentService(  # pylint: disable=too-few-public-methods
    IRelationalService[AdjustmentDE],
    IAdjustmentService,
):
    """A CRUD service for billing adjustments."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=AdjustmentDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

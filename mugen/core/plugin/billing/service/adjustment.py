"""Provides a CRUD service for billing adjustments."""

__all__ = ["AdjustmentService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.plugin.billing.contract.service.adjustment import IAdjustmentService
from mugen.core.plugin.billing.domain import AdjustmentDE
from mugen.core.plugin.billing.service.reference import BillingReferenceService


class AdjustmentService(  # pylint: disable=too-few-public-methods
    BillingReferenceService[AdjustmentDE],
    IAdjustmentService,
):
    """A CRUD service for billing adjustments."""

    _currency_snapshot = True
    _active_reference_tables = {
        "currency_definition_id": (
            "billing_currency_definition",
            "CurrencyDefinitionId",
        ),
    }

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=AdjustmentDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

"""Provides a CRUD service for billing runs."""

__all__ = ["BillingRunService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.billing.contract.service.billing_run import IBillingRunService
from mugen.core.plugin.billing.domain import BillingRunDE


class BillingRunService(  # pylint: disable=too-few-public-methods
    IRelationalService[BillingRunDE],
    IBillingRunService,
):
    """A CRUD service for billing runs."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=BillingRunDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

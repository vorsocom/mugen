"""Provides a CRUD service for billing accounts."""

__all__ = ["AccountService"]

from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway

from mugen.core.plugin.billing.contract.service.account import IAccountService
from mugen.core.plugin.billing.domain import AccountDE


class AccountService(  # pylint: disable=too-few-public-methods
    IRelationalService[AccountDE],
    IAccountService,
):
    """A CRUD service for billing accounts."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=AccountDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

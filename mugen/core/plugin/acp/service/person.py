"""Provides a service for the Person declarative model."""

__all__ = ["PersonService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.contract.service import IPersonService
from mugen.core.plugin.acp.domain import PersonDE


class PersonService(
    IRelationalService[PersonDE],
    IPersonService,
):
    """A service for the Person declarative model."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=PersonDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

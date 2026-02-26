"""Provides a CRUD service for retention classes."""

__all__ = ["RetentionClassService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_governance.contract.service.retention_class import (
    IRetentionClassService,
)
from mugen.core.plugin.ops_governance.domain import RetentionClassDE


class RetentionClassService(  # pylint: disable=too-few-public-methods
    IRelationalService[RetentionClassDE],
    IRetentionClassService,
):
    """A CRUD service for retention class metadata."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=RetentionClassDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

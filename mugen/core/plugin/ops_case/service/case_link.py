"""Provides a CRUD service for case links."""

__all__ = ["CaseLinkService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_case.contract.service.case_link import ICaseLinkService
from mugen.core.plugin.ops_case.domain import CaseLinkDE


class CaseLinkService(  # pylint: disable=too-few-public-methods
    IRelationalService[CaseLinkDE],
    ICaseLinkService,
):
    """A CRUD service for case links."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=CaseLinkDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )


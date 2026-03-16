"""Provides a CRUD service for taxonomy categories."""

__all__ = ["TaxonomyCategoryService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService

from mugen.core.plugin.ops_vpn.contract.service.taxonomy_category import (
    ITaxonomyCategoryService,
)
from mugen.core.plugin.ops_vpn.domain import TaxonomyCategoryDE


class TaxonomyCategoryService(  # pylint: disable=too-few-public-methods
    IRelationalService[TaxonomyCategoryDE],
    ITaxonomyCategoryService,
):
    """A CRUD service for taxonomy categories."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=TaxonomyCategoryDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

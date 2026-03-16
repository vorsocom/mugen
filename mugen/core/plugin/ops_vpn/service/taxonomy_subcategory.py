"""Provides a CRUD service for taxonomy subcategories."""

__all__ = ["TaxonomySubcategoryService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService

from mugen.core.plugin.ops_vpn.contract.service.taxonomy_subcategory import (
    ITaxonomySubcategoryService,
)
from mugen.core.plugin.ops_vpn.domain import TaxonomySubcategoryDE


class TaxonomySubcategoryService(  # pylint: disable=too-few-public-methods
    IRelationalService[TaxonomySubcategoryDE],
    ITaxonomySubcategoryService,
):
    """A CRUD service for taxonomy subcategories."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=TaxonomySubcategoryDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

"""Provides a CRUD service for taxonomy domains."""

__all__ = ["TaxonomyDomainService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService

from mugen.core.plugin.ops_vpn.contract.service.taxonomy_domain import (
    ITaxonomyDomainService,
)
from mugen.core.plugin.ops_vpn.domain import TaxonomyDomainDE


class TaxonomyDomainService(  # pylint: disable=too-few-public-methods
    IRelationalService[TaxonomyDomainDE],
    ITaxonomyDomainService,
):
    """A CRUD service for taxonomy domains."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=TaxonomyDomainDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

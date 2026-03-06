"""Provides a CRUD service for ingress bindings."""

__all__ = ["IngressBindingService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.channel_orchestration.contract.service.ingress_binding import (
    IIngressBindingService,
)
from mugen.core.plugin.channel_orchestration.domain import IngressBindingDE


class IngressBindingService(  # pylint: disable=too-few-public-methods
    IRelationalService[IngressBindingDE],
    IIngressBindingService,
):
    """A CRUD service for ingress bindings."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=IngressBindingDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

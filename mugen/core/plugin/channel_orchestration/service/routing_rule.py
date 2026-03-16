"""Provides a CRUD service for routing rules."""

__all__ = ["RoutingRuleService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.channel_orchestration.contract.service.routing_rule import (
    IRoutingRuleService,
)
from mugen.core.plugin.channel_orchestration.domain import RoutingRuleDE


class RoutingRuleService(  # pylint: disable=too-few-public-methods
    IRelationalService[RoutingRuleDE],
    IRoutingRuleService,
):
    """A CRUD service for routing rules."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=RoutingRuleDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

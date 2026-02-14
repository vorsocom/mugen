"""Provides a CRUD service for throttle rules."""

__all__ = ["ThrottleRuleService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.channel_orchestration.contract.service.throttle_rule import (
    IThrottleRuleService,
)
from mugen.core.plugin.channel_orchestration.domain import ThrottleRuleDE


class ThrottleRuleService(  # pylint: disable=too-few-public-methods
    IRelationalService[ThrottleRuleDE],
    IThrottleRuleService,
):
    """A CRUD service for throttle rules."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=ThrottleRuleDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

"""Provides a CRUD service for intake rules."""

__all__ = ["IntakeRuleService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.channel_orchestration.contract.service.intake_rule import (
    IIntakeRuleService,
)
from mugen.core.plugin.channel_orchestration.domain import IntakeRuleDE


class IntakeRuleService(  # pylint: disable=too-few-public-methods
    IRelationalService[IntakeRuleDE],
    IIntakeRuleService,
):
    """A CRUD service for intake rules."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=IntakeRuleDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

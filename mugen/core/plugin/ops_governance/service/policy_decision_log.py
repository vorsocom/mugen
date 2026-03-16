"""Provides a CRUD service for policy decision logs."""

__all__ = ["PolicyDecisionLogService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_governance.contract.service.policy_decision_log import (
    IPolicyDecisionLogService,
)
from mugen.core.plugin.ops_governance.domain import PolicyDecisionLogDE


class PolicyDecisionLogService(  # pylint: disable=too-few-public-methods
    IRelationalService[PolicyDecisionLogDE],
    IPolicyDecisionLogService,
):
    """A CRUD service for append-only policy decision logs."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=PolicyDecisionLogDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

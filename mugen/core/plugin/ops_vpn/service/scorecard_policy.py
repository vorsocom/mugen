"""Provides a CRUD service for scorecard policies."""

__all__ = ["ScorecardPolicyService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_vpn.contract.service.scorecard_policy import (
    IScorecardPolicyService,
)
from mugen.core.plugin.ops_vpn.domain import ScorecardPolicyDE


class ScorecardPolicyService(  # pylint: disable=too-few-public-methods
    IRelationalService[ScorecardPolicyDE],
    IScorecardPolicyService,
):
    """A CRUD service for scorecard policies."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=ScorecardPolicyDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

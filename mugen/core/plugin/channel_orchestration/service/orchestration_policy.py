"""Provides a CRUD service for orchestration policies."""

__all__ = ["OrchestrationPolicyService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from ..contract.service.orchestration_policy import IOrchestrationPolicyService
from ..domain import OrchestrationPolicyDE


class OrchestrationPolicyService(  # pylint: disable=too-few-public-methods
    IRelationalService[OrchestrationPolicyDE],
    IOrchestrationPolicyService,
):
    """A CRUD service for orchestration policies."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=OrchestrationPolicyDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

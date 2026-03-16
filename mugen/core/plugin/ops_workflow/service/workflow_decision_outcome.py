"""Provides a CRUD service for workflow decision outcomes."""

__all__ = ["WorkflowDecisionOutcomeService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_workflow.contract.service.workflow_decision_outcome import (
    IWorkflowDecisionOutcomeService,
)
from mugen.core.plugin.ops_workflow.domain import WorkflowDecisionOutcomeDE


class WorkflowDecisionOutcomeService(  # pylint: disable=too-few-public-methods
    IRelationalService[WorkflowDecisionOutcomeDE],
    IWorkflowDecisionOutcomeService,
):
    """A CRUD service for append-only workflow decision outcomes."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=WorkflowDecisionOutcomeDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

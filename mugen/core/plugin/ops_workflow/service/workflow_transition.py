"""Provides a CRUD service for workflow transitions."""

__all__ = ["WorkflowTransitionService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_workflow.contract.service.workflow_transition import (
    IWorkflowTransitionService,
)
from mugen.core.plugin.ops_workflow.domain import WorkflowTransitionDE


class WorkflowTransitionService(  # pylint: disable=too-few-public-methods
    IRelationalService[WorkflowTransitionDE],
    IWorkflowTransitionService,
):
    """A CRUD service for workflow transitions."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=WorkflowTransitionDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

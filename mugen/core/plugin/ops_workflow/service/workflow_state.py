"""Provides a CRUD service for workflow states."""

__all__ = ["WorkflowStateService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_workflow.contract.service.workflow_state import (
    IWorkflowStateService,
)
from mugen.core.plugin.ops_workflow.domain import WorkflowStateDE


class WorkflowStateService(  # pylint: disable=too-few-public-methods
    IRelationalService[WorkflowStateDE],
    IWorkflowStateService,
):
    """A CRUD service for workflow states."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=WorkflowStateDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

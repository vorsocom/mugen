"""Provides a CRUD service for workflow definitions."""

__all__ = ["WorkflowDefinitionService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_workflow.contract.service.workflow_definition import (
    IWorkflowDefinitionService,
)
from mugen.core.plugin.ops_workflow.domain import WorkflowDefinitionDE


class WorkflowDefinitionService(  # pylint: disable=too-few-public-methods
    IRelationalService[WorkflowDefinitionDE],
    IWorkflowDefinitionService,
):
    """A CRUD service for workflow definitions."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=WorkflowDefinitionDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

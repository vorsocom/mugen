"""Provides a CRUD service for workflow versions."""

__all__ = ["WorkflowVersionService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_workflow.contract.service.workflow_version import (
    IWorkflowVersionService,
)
from mugen.core.plugin.ops_workflow.domain import WorkflowVersionDE


class WorkflowVersionService(  # pylint: disable=too-few-public-methods
    IRelationalService[WorkflowVersionDE],
    IWorkflowVersionService,
):
    """A CRUD service for workflow versions."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=WorkflowVersionDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

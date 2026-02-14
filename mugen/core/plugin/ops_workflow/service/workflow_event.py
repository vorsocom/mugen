"""Provides a CRUD service for append-only workflow events."""

__all__ = ["WorkflowEventService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_workflow.contract.service.workflow_event import (
    IWorkflowEventService,
)
from mugen.core.plugin.ops_workflow.domain import WorkflowEventDE


class WorkflowEventService(  # pylint: disable=too-few-public-methods
    IRelationalService[WorkflowEventDE],
    IWorkflowEventService,
):
    """A CRUD service for append-only workflow events."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=WorkflowEventDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

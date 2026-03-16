"""Provides a CRUD service for workflow action replay/dedup ledger rows."""

__all__ = ["WorkflowActionDedupService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_workflow.domain import WorkflowActionDedupDE


class WorkflowActionDedupService(  # pylint: disable=too-few-public-methods
    IRelationalService[WorkflowActionDedupDE],
):
    """A CRUD service for workflow action dedup records."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=WorkflowActionDedupDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

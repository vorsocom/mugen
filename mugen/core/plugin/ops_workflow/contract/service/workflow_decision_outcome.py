"""Provides a service contract for WorkflowDecisionOutcomeDE services."""

__all__ = ["IWorkflowDecisionOutcomeService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_workflow.domain import WorkflowDecisionOutcomeDE


class IWorkflowDecisionOutcomeService(
    ICrudService[WorkflowDecisionOutcomeDE],
    ABC,
):
    """A service contract for workflow decision outcome services."""

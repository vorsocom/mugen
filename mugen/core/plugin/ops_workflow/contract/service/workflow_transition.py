"""Provides a service contract for WorkflowTransitionDE-related services."""

__all__ = ["IWorkflowTransitionService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_workflow.domain import WorkflowTransitionDE


class IWorkflowTransitionService(
    ICrudService[WorkflowTransitionDE],
    ABC,
):
    """A service contract for WorkflowTransitionDE-related services."""

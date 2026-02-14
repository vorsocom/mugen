"""Provides a service contract for WorkflowStateDE-related services."""

__all__ = ["IWorkflowStateService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_workflow.domain import WorkflowStateDE


class IWorkflowStateService(
    ICrudService[WorkflowStateDE],
    ABC,
):
    """A service contract for WorkflowStateDE-related services."""

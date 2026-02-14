"""Provides a service contract for WorkflowEventDE-related services."""

__all__ = ["IWorkflowEventService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_workflow.domain import WorkflowEventDE


class IWorkflowEventService(
    ICrudService[WorkflowEventDE],
    ABC,
):
    """A service contract for WorkflowEventDE-related services."""

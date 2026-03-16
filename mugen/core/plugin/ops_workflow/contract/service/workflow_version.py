"""Provides a service contract for WorkflowVersionDE-related services."""

__all__ = ["IWorkflowVersionService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_workflow.domain import WorkflowVersionDE


class IWorkflowVersionService(
    ICrudService[WorkflowVersionDE],
    ABC,
):
    """A service contract for WorkflowVersionDE-related services."""

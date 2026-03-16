"""Provides a service contract for WorkflowDefinitionDE-related services."""

__all__ = ["IWorkflowDefinitionService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_workflow.domain import WorkflowDefinitionDE


class IWorkflowDefinitionService(
    ICrudService[WorkflowDefinitionDE],
    ABC,
):
    """A service contract for WorkflowDefinitionDE-related services."""

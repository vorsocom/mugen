"""Provides a service contract for WorkflowTaskDE-related services."""

__all__ = ["IWorkflowTaskService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.ops_workflow.domain import WorkflowTaskDE


class IWorkflowTaskService(
    ICrudService[WorkflowTaskDE],
    ABC,
):
    """A service contract for WorkflowTaskDE-related services."""

    @abstractmethod
    async def action_assign_task(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Assign or hand off a workflow task."""

    @abstractmethod
    async def action_complete_task(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Complete a workflow task."""

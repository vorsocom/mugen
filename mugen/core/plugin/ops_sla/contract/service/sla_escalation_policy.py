"""Provides a service contract for SlaEscalationPolicyDE-related services."""

__all__ = ["ISlaEscalationPolicyService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.ops_sla.domain import SlaEscalationPolicyDE


class ISlaEscalationPolicyService(
    ICrudService[SlaEscalationPolicyDE],
    ABC,
):
    """A service contract for SlaEscalationPolicyDE-related services."""

    @abstractmethod
    async def action_evaluate(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
        entity_id: uuid.UUID | None = None,
    ) -> tuple[dict[str, Any], int]:
        """Evaluate triggers and return candidate actions."""

    @abstractmethod
    async def action_execute(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
        entity_id: uuid.UUID | None = None,
    ) -> tuple[dict[str, Any], int]:
        """Evaluate and persist escalation run records with per-action results."""

    @abstractmethod
    async def action_test(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
        entity_id: uuid.UUID | None = None,
    ) -> tuple[dict[str, Any], int]:
        """Evaluate a single policy/sample pair without side effects."""

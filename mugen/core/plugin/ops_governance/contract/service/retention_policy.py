"""Provides a service contract for RetentionPolicyDE-related services."""

__all__ = ["IRetentionPolicyService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.ops_governance.domain import RetentionPolicyDE


class IRetentionPolicyService(ICrudService[RetentionPolicyDE], ABC):
    """A service contract for RetentionPolicyDE-related services."""

    @abstractmethod
    async def action_apply_retention_action(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Apply a metadata-only retention action."""

    @abstractmethod
    async def action_run_lifecycle(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Run retention/legal-hold lifecycle orchestration for scoped resources."""

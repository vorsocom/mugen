"""Provides a service contract for PermissionType-related services."""

__all__ = ["IPermissionTypeService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.domain import PermissionTypeDE


class IPermissionTypeService(
    ICrudService[PermissionTypeDE],
    ABC,
):
    """A service contract for PermissionType-related services."""

    @abstractmethod
    async def entity_action_deprecate(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Deprecate a permission type."""

    @abstractmethod
    async def entity_action_reactivate(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Reactivate a permission type."""

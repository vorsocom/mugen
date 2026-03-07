"""Provides a service contract for SystemFlag-related services."""

__all__ = ["ISystemFlagService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.domain import SystemFlagDE


class ISystemFlagService(
    ICrudService[SystemFlagDE],
    ABC,
):
    """A service contract for SystemFlag-related services."""

    @abstractmethod
    async def entity_set_action_reloadPlatformProfiles(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Reload live multi-profile platform runtimes."""

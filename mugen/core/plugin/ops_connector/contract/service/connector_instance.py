"""Provides a service contract for ConnectorInstanceDE-related services."""

__all__ = ["IConnectorInstanceService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.ops_connector.domain import ConnectorInstanceDE


class IConnectorInstanceService(
    ICrudService[ConnectorInstanceDE],
    ABC,
):
    """A service contract for ConnectorInstanceDE-related services."""

    @abstractmethod
    async def action_test_connection(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Execute a lightweight health check against the connector endpoint."""

    @abstractmethod
    async def action_invoke(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Invoke a configured connector capability with retry + call logging."""

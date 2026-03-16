"""Provides a service contract for SchemaDefinition-related services."""

__all__ = ["ISchemaDefinitionService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.domain import SchemaDefinitionDE


class ISchemaDefinitionService(ICrudService[SchemaDefinitionDE], ABC):
    """A service contract for schema definition services."""

    @abstractmethod
    async def entity_set_action_validate(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Validate payload against a registered schema."""

    @abstractmethod
    async def action_validate(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Validate payload for a tenant-scoped schema reference."""

    @abstractmethod
    async def entity_set_action_coerce(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Apply schema defaults without aggressive type coercion."""

    @abstractmethod
    async def action_coerce(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Coerce payload defaults for tenant-scoped schema references."""

    @abstractmethod
    async def entity_set_action_activate_version(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Activate a schema version and deactivate prior active version."""

    @abstractmethod
    async def action_activate_version(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Tenant-scoped schema version activation."""

"""Provides a service contract for AuditEventDE-related services."""

__all__ = ["IAuditEventService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.audit.domain import AuditEventDE


class IAuditEventService(ICrudService[AuditEventDE], ABC):
    """A service contract for AuditEventDE-related services."""

    @abstractmethod
    async def entity_action_place_legal_hold(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Place a legal hold on a non-tenant audit event."""

    @abstractmethod
    async def action_place_legal_hold(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Place a legal hold on a tenant-scoped audit event."""

    @abstractmethod
    async def entity_action_release_legal_hold(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Release legal hold on a non-tenant audit event."""

    @abstractmethod
    async def action_release_legal_hold(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Release legal hold on a tenant-scoped audit event."""

    @abstractmethod
    async def entity_action_redact(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Redact snapshots on a non-tenant audit event."""

    @abstractmethod
    async def action_redact(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Redact snapshots on a tenant-scoped audit event."""

    @abstractmethod
    async def entity_action_tombstone(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Tombstone a non-tenant audit event."""

    @abstractmethod
    async def action_tombstone(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Tombstone a tenant-scoped audit event."""

    @abstractmethod
    async def entity_set_action_run_lifecycle(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Run lifecycle phases for non-tenant audit rows."""

    @abstractmethod
    async def action_run_lifecycle(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Run lifecycle phases for tenant-scoped audit rows."""

    @abstractmethod
    async def entity_set_action_verify_chain(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Verify non-tenant audit hash-chain integrity."""

    @abstractmethod
    async def action_verify_chain(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Verify tenant-scoped audit hash-chain integrity."""

    @abstractmethod
    async def entity_set_action_seal_backlog(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Seal non-tenant backlog rows missing chain metadata."""

    @abstractmethod
    async def action_seal_backlog(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Seal tenant-scoped backlog rows missing chain metadata."""

"""Provides a service contract for EvidenceBlob services."""

__all__ = ["IEvidenceBlobService"]

from datetime import datetime
import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.audit.domain import EvidenceBlobDE


class IEvidenceBlobService(ICrudService[EvidenceBlobDE], ABC):
    """A service contract for evidence metadata lifecycle operations."""

    @abstractmethod
    async def entity_set_action_register(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Register evidence metadata in global scope."""

    @abstractmethod
    async def action_register(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Register evidence metadata in tenant scope."""

    @abstractmethod
    async def entity_action_verify_hash(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Verify stored hash metadata in global scope."""

    @abstractmethod
    async def action_verify_hash(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Verify stored hash metadata in tenant scope."""

    @abstractmethod
    async def entity_action_place_legal_hold(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Place legal hold in global scope."""

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
        """Place legal hold in tenant scope."""

    @abstractmethod
    async def entity_action_release_legal_hold(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Release legal hold in global scope."""

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
        """Release legal hold in tenant scope."""

    @abstractmethod
    async def entity_action_redact(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Redact evidence in global scope."""

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
        """Redact evidence in tenant scope."""

    @abstractmethod
    async def entity_action_tombstone(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Tombstone evidence in global scope."""

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
        """Tombstone evidence in tenant scope."""

    @abstractmethod
    async def entity_action_purge(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Mark evidence as purged in global scope."""

    @abstractmethod
    async def action_purge(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Mark evidence as purged in tenant scope."""

    @abstractmethod
    async def run_lifecycle(
        self,
        *,
        tenant_id: uuid.UUID | None,
        dry_run: bool,
        batch_size: int,
        max_batches: int,
        now_override: datetime | None = None,
        purge_grace_days_override: int | None = None,
    ) -> dict[str, Any]:
        """Execute deterministic lifecycle phases for evidence blobs."""

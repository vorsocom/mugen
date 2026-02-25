"""Provides a service contract for DedupRecord-related services."""

__all__ = ["IDedupRecordService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.domain import DedupRecordDE


class IDedupRecordService(ICrudService[DedupRecordDE], ABC):
    """A service contract for dedup ledger services."""

    @abstractmethod
    async def entity_set_action_acquire(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Acquire (or replay) a dedup ledger record."""

    @abstractmethod
    async def action_acquire(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Acquire (or replay) a tenant-scoped dedup ledger record."""

    @abstractmethod
    async def entity_action_commit_success(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Commit successful idempotent execution to a dedup record."""

    @abstractmethod
    async def action_commit_success(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Commit successful tenant-scoped execution."""

    @abstractmethod
    async def entity_action_commit_failure(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Commit failed idempotent execution to a dedup record."""

    @abstractmethod
    async def action_commit_failure(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Commit failed tenant-scoped execution."""

    @abstractmethod
    async def entity_set_action_sweep_expired(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Sweep expired dedup records in bounded batches."""

    @abstractmethod
    async def action_sweep_expired(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Sweep expired tenant-scoped dedup records."""

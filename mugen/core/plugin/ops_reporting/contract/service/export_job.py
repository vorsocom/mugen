"""Provides a service contract for ExportJobDE-related services."""

__all__ = ["IExportJobService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.ops_reporting.domain import ExportJobDE


class IExportJobService(
    ICrudService[ExportJobDE],
    ABC,
):
    """A service contract for export-job lifecycle actions."""

    @abstractmethod
    async def action_create_export(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Create a queued export job for the tenant."""

    @abstractmethod
    async def action_build_export(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Build export items, proofs, and final signed manifest."""

    @abstractmethod
    async def action_verify_export(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Verify persisted export items, manifest hash, and signature."""

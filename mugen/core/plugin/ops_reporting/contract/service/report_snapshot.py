"""Provides a service contract for ReportSnapshotDE-related services."""

__all__ = ["IReportSnapshotService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.ops_reporting.domain import ReportSnapshotDE


class IReportSnapshotService(
    ICrudService[ReportSnapshotDE],
    ABC,
):
    """A service contract for ReportSnapshotDE-related services."""

    @abstractmethod
    async def action_generate_snapshot(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Generate point-in-time report payload from aggregated metric series."""

    @abstractmethod
    async def action_publish_snapshot(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Mark a generated snapshot as published."""

    @abstractmethod
    async def action_archive_snapshot(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Archive a snapshot for retention lifecycle management."""

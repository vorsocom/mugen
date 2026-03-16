"""Provides a service contract for MetricDefinitionDE-related services."""

__all__ = ["IMetricDefinitionService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.ops_reporting.domain import MetricDefinitionDE


class IMetricDefinitionService(
    ICrudService[MetricDefinitionDE],
    ABC,
):
    """A service contract for MetricDefinitionDE-related services."""

    @abstractmethod
    async def action_run_aggregation(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Run deterministic metric aggregation over a requested window."""

    @abstractmethod
    async def action_recompute_window(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Force recomputation for a metric/window/scope key."""

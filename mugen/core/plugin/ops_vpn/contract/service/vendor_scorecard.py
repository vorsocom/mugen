"""Provides a service contract for VendorScorecardDE-related services."""

__all__ = ["IVendorScorecardService"]

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.ops_vpn.domain import VendorScorecardDE


class IVendorScorecardService(
    ICrudService[VendorScorecardDE],
    ABC,
):
    """A service contract for VendorScorecardDE-related services."""

    @abstractmethod
    async def action_rollup(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> dict[str, Any]:
        """Roll up a scorecard snapshot for a vendor and period."""

    @abstractmethod
    async def rollup_period(
        self,
        *,
        tenant_id: uuid.UUID,
        vendor_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
    ) -> VendorScorecardDE:
        """Roll up and persist a period snapshot."""

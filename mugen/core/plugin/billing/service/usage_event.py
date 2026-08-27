"""Provides a CRUD service for billing usage events."""

__all__ = ["UsageEventService"]

from typing import Any, Mapping

from quart import abort

from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway

from mugen.core.plugin.billing.contract.service.usage_event import IUsageEventService
from mugen.core.plugin.billing.domain import UsageEventDE


class UsageEventService(  # pylint: disable=too-few-public-methods
    IRelationalService[UsageEventDE],
    IUsageEventService,
):
    """A CRUD service for billing usage events."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=UsageEventDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def create(self, values: Mapping[str, Any]) -> UsageEventDE:
        payload = dict(values)
        meter = await self._rsg.get_one(
            "billing_meter_definition",
            {"id": payload["meter_definition_id"]},
        )
        if meter is None or not meter.get("is_active"):
            abort(400, "MeterDefinitionId must reference an active global meter.")
        payload["meter_code"] = meter["code"]
        return await super().create(payload)

"""Provides a CRUD service for meter policies."""

__all__ = ["MeterPolicyService"]

from typing import Any, Mapping

from quart import abort

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_metering.contract.service.meter_policy import (
    IMeterPolicyService,
)
from mugen.core.plugin.ops_metering.domain import MeterPolicyDE


class MeterPolicyService(  # pylint: disable=too-few-public-methods
    IRelationalService[MeterPolicyDE],
    IMeterPolicyService,
):
    """A CRUD service for metering policy definitions."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=MeterPolicyDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def create(self, values: Mapping[str, Any]) -> MeterPolicyDE:
        meter = await self._rsg.get_one(
            "billing_meter_definition",
            {"id": values["meter_definition_id"]},
        )
        if meter is None or not meter.get("is_active"):
            abort(400, "MeterDefinitionId must reference an active global meter.")
        return await super().create(values)

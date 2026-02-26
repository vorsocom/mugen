"""Provides a CRUD service for connector type registry rows."""

__all__ = ["ConnectorTypeService"]

from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_connector.contract.service.connector_type import (
    IConnectorTypeService,
)
from mugen.core.plugin.ops_connector.domain import ConnectorTypeDE


class ConnectorTypeService(  # pragma: no cover
    IRelationalService[ConnectorTypeDE],
    IConnectorTypeService,
):
    """A CRUD service for globally-scoped connector type definitions."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=ConnectorTypeDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def create(self, values: Mapping[str, Any]) -> ConnectorTypeDE:
        payload = dict(values)
        payload["key"] = str(payload.get("key") or "").strip()
        payload["display_name"] = str(payload.get("display_name") or "").strip()
        payload["adapter_kind"] = (
            str(payload.get("adapter_kind") or "http_json").strip().lower()
        )
        if payload.get("capabilities_json") is None:
            payload["capabilities_json"] = {}
        return await super().create(payload)

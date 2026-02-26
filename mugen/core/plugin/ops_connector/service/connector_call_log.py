"""Provides a CRUD service for immutable connector call-log rows."""

__all__ = ["ConnectorCallLogService"]

from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_connector.contract.service.connector_call_log import (
    IConnectorCallLogService,
)
from mugen.core.plugin.ops_connector.domain import ConnectorCallLogDE


class ConnectorCallLogService(  # pragma: no cover
    IRelationalService[ConnectorCallLogDE],
    IConnectorCallLogService,
):
    """A CRUD service for append-only connector invocation call logs."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=ConnectorCallLogDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def create(self, values: Mapping[str, Any]) -> ConnectorCallLogDE:
        payload = dict(values)
        payload["trace_id"] = str(payload.get("trace_id") or "").strip()
        payload["capability_name"] = str(payload.get("capability_name") or "").strip()
        payload["request_hash"] = str(payload.get("request_hash") or "").strip()

        response_hash = payload.get("response_hash")
        if response_hash is not None:
            payload["response_hash"] = str(response_hash).strip() or None

        client_action_key = payload.get("client_action_key")
        if client_action_key is not None:
            payload["client_action_key"] = str(client_action_key).strip() or None

        return await super().create(payload)

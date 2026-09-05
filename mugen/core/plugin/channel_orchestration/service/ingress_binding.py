"""Provides a CRUD service for ingress bindings."""

__all__ = ["IngressBindingService"]

from collections.abc import Mapping
from typing import Any

from quart import abort

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.channel_orchestration.contract.service.ingress_binding import (
    IIngressBindingService,
)
from mugen.core.plugin.channel_orchestration.domain import IngressBindingDE


class IngressBindingService(  # pylint: disable=too-few-public-methods
    IRelationalService[IngressBindingDE],
    IIngressBindingService,
):
    """A CRUD service for ingress bindings."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=IngressBindingDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def _validate_ownership(self, values: Mapping[str, Any]) -> None:
        """Prove messaging identifiers belong to the binding's tenant and client."""
        channel_key = str(values.get("channel_key") or "").strip().casefold()
        identifier_type = str(values.get("identifier_type") or "").strip().casefold()
        identifier_value = str(values.get("identifier_value") or "").strip()
        if not channel_key or not identifier_type or not identifier_value:
            abort(400, "ChannelKey, IdentifierType and IdentifierValue are required.")
        messaging_channels = {
            "line",
            "matrix",
            "signal",
            "telegram",
            "wechat",
            "whatsapp",
        }
        profile_id = values.get("channel_profile_id")
        if profile_id is None and channel_key not in messaging_channels:
            return
        profile = await self._rsg.get_one(
            "channel_orchestration_channel_profile",
            {
                "tenant_id": values.get("tenant_id"),
                "id": profile_id,
                "channel_key": channel_key,
                "is_active": True,
            },
        )
        if profile is None:
            abort(
                400, "ChannelProfileId must reference an active tenant-owned channel."
            )
        if channel_key not in messaging_channels:
            return
        if identifier_type not in {
            "path_token",
            "recipient_user_id",
            "account_number",
            "phone_number_id",
        }:
            abort(400, "IdentifierType is not a messaging client identifier.")
        client_profile = await self._rsg.get_one(
            "admin_messaging_client_profile",
            {
                "tenant_id": values.get("tenant_id"),
                "id": profile.get("client_profile_id"),
                "platform_key": channel_key,
                "is_active": True,
                identifier_type: identifier_value,
            },
        )
        if client_profile is None:
            abort(400, "IdentifierValue is not owned by the channel's client profile.")

    async def create(self, values: Mapping[str, Any]) -> IngressBindingDE:
        await self._validate_ownership(values)
        return await super().create(values)

    async def _validated_changes(
        self,
        where: Mapping[str, Any],
        changes: Mapping[str, Any],
    ) -> bool:
        current = await self.get(where)
        if current is None:
            return False
        if dict(changes) == {"is_active": False}:
            return True
        values = {
            "tenant_id": current.tenant_id,
            "channel_profile_id": current.channel_profile_id,
            "channel_key": current.channel_key,
            "identifier_type": current.identifier_type,
            "identifier_value": current.identifier_value,
        }
        values.update(changes)
        await self._validate_ownership(values)
        return True

    async def update(
        self,
        where: Mapping[str, Any],
        changes: Mapping[str, Any],
    ) -> IngressBindingDE | None:
        if not await self._validated_changes(where, changes):
            return None
        return await super().update(where, changes)

    async def update_with_row_version(
        self,
        where: Mapping[str, Any],
        *,
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> IngressBindingDE | None:
        if not await self._validated_changes(where, changes):
            return None
        return await super().update_with_row_version(
            where,
            expected_row_version=expected_row_version,
            changes=changes,
        )

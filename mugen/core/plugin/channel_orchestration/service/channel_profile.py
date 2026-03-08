"""Provides a CRUD service for channel profiles."""

__all__ = ["ChannelProfileService"]

from collections.abc import Mapping
from typing import Any
import uuid

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.channel_orchestration.contract.service.channel_profile import (
    IChannelProfileService,
)
from mugen.core.plugin.channel_orchestration.domain import ChannelProfileDE
from mugen.core.plugin.acp.service.messaging_client_profile import (
    MessagingClientProfileService,
)


class ChannelProfileService(  # pylint: disable=too-few-public-methods
    IRelationalService[ChannelProfileDE],
    IChannelProfileService,
):
    """A CRUD service for channel profiles."""

    _client_profile_channels = frozenset(
        {
            "line",
            "matrix",
            "signal",
            "telegram",
            "wechat",
            "whatsapp",
        }
    )

    def __init__(
        self,
        table: str,
        rsg: IRelationalStorageGateway,
        **kwargs,
    ):
        self._messaging_client_profile_service = MessagingClientProfileService(
            table="admin_messaging_client_profile",
            rsg=rsg,
        )
        super().__init__(
            de_type=ChannelProfileDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    @staticmethod
    def _normalize_optional_text(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _normalize_optional_uuid(value: object) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value).strip())
        except (AttributeError, TypeError, ValueError):
            return None

    async def _validate_client_profile_id(
        self,
        *,
        channel_key: str | None,
        tenant_id: object,
        client_profile_id: object,
    ) -> uuid.UUID | None:
        normalized_channel_key = self._normalize_optional_text(channel_key)
        normalized_client_profile_id = self._normalize_optional_uuid(client_profile_id)

        if normalized_channel_key not in self._client_profile_channels:
            return normalized_client_profile_id

        if normalized_client_profile_id is None:
            raise RuntimeError(
                "ClientProfileId is required for non-web messaging channel profiles."
            )

        tenant_uuid = self._normalize_optional_uuid(tenant_id)
        if tenant_uuid is None:
            raise RuntimeError(
                "TenantId is required to validate ClientProfileId."
            )

        client_profile = await self._messaging_client_profile_service.get(
            {
                "tenant_id": tenant_uuid,
                "id": normalized_client_profile_id,
                "is_active": True,
            }
        )
        if client_profile is None:
            raise RuntimeError(
                "Unknown ClientProfileId for channel profile "
                f"(channel_key={normalized_channel_key!r} "
                f"client_profile_id={str(normalized_client_profile_id)!r})."
            )
        if client_profile.platform_key != normalized_channel_key:
            raise RuntimeError(
                "ClientProfileId platform does not match ChannelKey "
                f"(channel_key={normalized_channel_key!r} "
                f"platform_key={client_profile.platform_key!r})."
            )
        return normalized_client_profile_id

    async def create(self, values: Mapping[str, Any]) -> ChannelProfileDE:
        payload = dict(values)
        payload["client_profile_id"] = await self._validate_client_profile_id(
            channel_key=payload.get("channel_key"),
            tenant_id=payload.get("tenant_id"),
            client_profile_id=payload.get("client_profile_id"),
        )
        return await super().create(payload)

    async def update(
        self,
        where: Mapping[str, Any],
        changes: Mapping[str, Any],
    ) -> ChannelProfileDE | None:
        current = await self.get(where)
        if current is None:
            return None

        payload = dict(changes)
        payload["client_profile_id"] = await self._validate_client_profile_id(
            channel_key=payload.get("channel_key", current.channel_key),
            tenant_id=payload.get("tenant_id", current.tenant_id),
            client_profile_id=payload.get(
                "client_profile_id",
                current.client_profile_id,
            ),
        )
        return await super().update(where, payload)

    async def update_with_row_version(
        self,
        where: Mapping[str, Any],
        *,
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> ChannelProfileDE | None:
        current = await self.get(where)
        if current is None:
            return None

        payload = dict(changes)
        payload["client_profile_id"] = await self._validate_client_profile_id(
            channel_key=payload.get("channel_key", current.channel_key),
            tenant_id=payload.get("tenant_id", current.tenant_id),
            client_profile_id=payload.get(
                "client_profile_id",
                current.client_profile_id,
            ),
        )
        return await super().update_with_row_version(
            where,
            expected_row_version=expected_row_version,
            changes=payload,
        )

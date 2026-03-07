"""Provides a CRUD service for channel profiles."""

__all__ = ["ChannelProfileService"]

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from mugen.core import di
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.channel_orchestration.contract.service.channel_profile import (
    IChannelProfileService,
)
from mugen.core.plugin.channel_orchestration.domain import ChannelProfileDE
from mugen.core.utility.platform_runtime_profile import (
    get_platform_runtime_profile_keys,
    normalize_runtime_profile_key,
)


class ChannelProfileService(  # pylint: disable=too-few-public-methods
    IRelationalService[ChannelProfileDE],
    IChannelProfileService,
):
    """A CRUD service for channel profiles."""

    _runtime_profile_channels = frozenset(
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
        config: SimpleNamespace | None = None,
        **kwargs,
    ):
        self._config = config
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

    def _resolve_config(self) -> SimpleNamespace | Mapping[str, Any] | None:
        if self._config is not None:
            return self._config
        try:
            return di.container.config
        except Exception:  # pylint: disable=broad-exception-caught
            return None

    def _validate_runtime_profile_key(
        self,
        *,
        channel_key: str | None,
        runtime_profile_key: str | None,
    ) -> str | None:
        normalized_channel_key = self._normalize_optional_text(channel_key)
        normalized_runtime_profile_key = normalize_runtime_profile_key(
            runtime_profile_key
        )

        if normalized_channel_key not in self._runtime_profile_channels:
            return normalized_runtime_profile_key

        if normalized_runtime_profile_key is None:
            raise RuntimeError(
                "RuntimeProfileKey is required for non-web messaging channel profiles."
            )

        config = self._resolve_config()
        if config is None:
            raise RuntimeError(
                "RuntimeProfileKey validation requires runtime configuration."
            )

        active_keys = get_platform_runtime_profile_keys(
            config,
            platform=normalized_channel_key,
        )
        if normalized_runtime_profile_key not in active_keys:
            raise RuntimeError(
                "Unknown RuntimeProfileKey for channel profile "
                f"(channel_key={normalized_channel_key!r} "
                f"runtime_profile_key={normalized_runtime_profile_key!r})."
            )
        return normalized_runtime_profile_key

    async def create(self, values: Mapping[str, Any]) -> ChannelProfileDE:
        payload = dict(values)
        payload["runtime_profile_key"] = self._validate_runtime_profile_key(
            channel_key=payload.get("channel_key"),
            runtime_profile_key=payload.get("runtime_profile_key"),
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
        payload["runtime_profile_key"] = self._validate_runtime_profile_key(
            channel_key=payload.get("channel_key", current.channel_key),
            runtime_profile_key=payload.get(
                "runtime_profile_key",
                current.runtime_profile_key,
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
        payload["runtime_profile_key"] = self._validate_runtime_profile_key(
            channel_key=payload.get("channel_key", current.channel_key),
            runtime_profile_key=payload.get(
                "runtime_profile_key",
                current.runtime_profile_key,
            ),
        )
        return await super().update_with_row_version(
            where,
            expected_row_version=expected_row_version,
            changes=payload,
        )

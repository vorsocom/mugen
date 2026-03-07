"""Shared helpers for multi-profile messaging client managers."""

from __future__ import annotations

__all__ = ["SimpleProfileClientManager"]

import asyncio
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from mugen.core.utility.platform_runtime_profile import (
    DEFAULT_RUNTIME_PROFILE_KEY,
    clone_config_with_platform_profile,
    get_active_runtime_profile_key,
    get_platform_profile_dicts,
    get_platform_runtime_profile_keys,
    normalize_runtime_profile_key,
)


class SimpleProfileClientManager:
    """Shared lifecycle and routing helpers for multi-profile platform clients."""

    def __init__(
        self,
        *,
        platform: str,
        client_cls: type,
        config: Mapping[str, Any] | SimpleNamespace,
        logging_gateway: Any = None,
        **client_kwargs: Any,
    ) -> None:
        self._platform = str(platform).strip().lower()
        self._client_cls = client_cls
        self._root_config = config
        self._logging_gateway = logging_gateway
        self._client_kwargs = dict(client_kwargs)
        self._lock = asyncio.Lock()
        self._initialized = False
        self._clients, self._profile_snapshots = self._build_profile_clients(config)

    def configured_runtime_profile_keys(self) -> tuple[str, ...]:
        """List configured runtime profile keys for the current platform."""
        return tuple(self._clients.keys())

    def _build_profile_clients(
        self,
        config: Mapping[str, Any] | SimpleNamespace,
    ) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        clients: dict[str, Any] = {}
        snapshots: dict[str, dict[str, Any]] = {}
        profile_keys = get_platform_runtime_profile_keys(config, platform=self._platform)
        profile_dicts = get_platform_profile_dicts(config, platform=self._platform)

        for index, runtime_profile_key in enumerate(profile_keys):
            profile_config = clone_config_with_platform_profile(
                config,
                platform=self._platform,
                runtime_profile_key=runtime_profile_key,
            )
            clients[runtime_profile_key] = self._client_cls(
                config=profile_config,
                **self._client_kwargs,
            )
            snapshots[runtime_profile_key] = dict(profile_dicts[index])

        if not clients:
            raise RuntimeError(
                f"No runtime profiles configured for platform {self._platform!r}."
            )
        return clients, snapshots

    async def _init_client_map(self, clients: Mapping[str, Any]) -> None:
        await asyncio.gather(
            *(client.init() for client in clients.values()),
            return_exceptions=False,
        )

    async def _verify_client_map(self, clients: Mapping[str, Any]) -> bool:
        results = await asyncio.gather(
            *(client.verify_startup() for client in clients.values()),
            return_exceptions=False,
        )
        return all(result is True for result in results)

    async def _close_client_map(self, clients: Mapping[str, Any]) -> None:
        if not clients:
            return
        await asyncio.gather(
            *(client.close() for client in clients.values()),
            return_exceptions=True,
        )

    def _resolve_runtime_profile_key(self, runtime_profile_key: str | None = None) -> str:
        requested_key = normalize_runtime_profile_key(runtime_profile_key)
        if requested_key is None:
            requested_key = get_active_runtime_profile_key()
        if requested_key is not None:
            if requested_key not in self._clients:
                raise RuntimeError(
                    f"Unknown runtime profile key for {self._platform}: "
                    f"{requested_key!r}."
                )
            return requested_key

        configured = tuple(self._clients.keys())
        if len(configured) == 1:
            return configured[0]
        if DEFAULT_RUNTIME_PROFILE_KEY in self._clients:
            return DEFAULT_RUNTIME_PROFILE_KEY
        raise RuntimeError(
            f"runtime_profile_key is required for multi-profile {self._platform} "
            "operations."
        )

    def _client_for(self, runtime_profile_key: str | None = None) -> Any:
        return self._clients[self._resolve_runtime_profile_key(runtime_profile_key)]

    async def init(self) -> None:
        async with self._lock:
            if self._initialized:
                return
            await self._init_client_map(self._clients)
            self._initialized = True

    async def verify_startup(self) -> bool:
        await self.init()
        async with self._lock:
            return await self._verify_client_map(self._clients)

    async def close(self) -> None:
        async with self._lock:
            current = self._clients
            self._clients = {}
            self._profile_snapshots = {}
            self._initialized = False
        await self._close_client_map(current)

    async def reload_profiles(
        self,
        config: Mapping[str, Any] | SimpleNamespace | None = None,
    ) -> dict[str, list[str]]:
        next_config = self._root_config if config is None else config
        next_clients, next_snapshots = self._build_profile_clients(next_config)

        try:
            await self._init_client_map(next_clients)
            verified = await self._verify_client_map(next_clients)
            if verified is not True:
                raise RuntimeError(
                    f"{self._platform} runtime profile startup probe failed."
                )
        except Exception:
            await self._close_client_map(next_clients)
            raise

        async with self._lock:
            current_clients = self._clients
            current_snapshots = self._profile_snapshots
            self._root_config = next_config
            self._clients = next_clients
            self._profile_snapshots = next_snapshots
            self._initialized = True

        await self._close_client_map(current_clients)

        before_keys = set(current_snapshots)
        after_keys = set(next_snapshots)
        updated = sorted(
            key
            for key in (before_keys & after_keys)
            if current_snapshots.get(key) != next_snapshots.get(key)
        )
        unchanged = sorted(
            key
            for key in (before_keys & after_keys)
            if current_snapshots.get(key) == next_snapshots.get(key)
        )
        return {
            "added": sorted(after_keys - before_keys),
            "removed": sorted(before_keys - after_keys),
            "updated": updated,
            "unchanged": unchanged,
        }

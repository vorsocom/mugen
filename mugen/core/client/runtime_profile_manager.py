"""Shared helpers for multi-profile messaging client managers."""

from __future__ import annotations

__all__ = ["MultiProfileClientCloseError", "SimpleProfileClientManager"]

import asyncio
from collections.abc import Mapping
import importlib
from types import SimpleNamespace
from typing import Any
import uuid

from mugen.core.utility.client_profile_runtime import (
    get_active_client_profile_id,
    normalize_client_profile_id,
)

MessagingClientProfileService = None


def _messaging_client_profile_service_class():
    service_class = MessagingClientProfileService
    if service_class is not None:
        return service_class
    module = importlib.import_module(
        "mugen.core.plugin.acp.service.messaging_client_profile"
    )
    return getattr(module, "MessagingClientProfileService")


class MultiProfileClientCloseError(RuntimeError):
    """Raised when one or more managed profile clients fail cleanup."""

    def __init__(
        self,
        *,
        platform: str,
        failures: Mapping[str, str],
    ) -> None:
        self.platform = str(platform).strip().lower()
        self.failures = dict(failures)
        details = "; ".join(
            f"{client_profile_id}={message}"
            for client_profile_id, message in sorted(self.failures.items())
        )
        super().__init__(
            f"{self.platform} client profile cleanup failed: {details}"
        )


def _close_failure_message(result: BaseException) -> str:
    return f"{type(result).__name__}: {result}"


async def _close_clients_fail_closed(
    *,
    platform: str,
    clients: Mapping[str, Any],
) -> None:
    if not clients:
        return

    items = tuple(clients.items())
    results = await asyncio.gather(
        *(client.close() for _client_profile_id, client in items),
        return_exceptions=True,
    )
    failures = {
        client_profile_id: _close_failure_message(result)
        for (client_profile_id, _client), result in zip(items, results, strict=True)
        if isinstance(result, BaseException)
    }
    if failures:
        raise MultiProfileClientCloseError(
            platform=platform,
            failures=failures,
        )


class SimpleProfileClientManager:
    """Shared lifecycle and routing helpers for ACP-owned platform clients."""

    def __init__(
        self,
        *,
        platform: str,
        client_cls: type,
        config: Mapping[str, Any] | SimpleNamespace,
        relational_storage_gateway: Any = None,
        logging_gateway: Any = None,
        **client_kwargs: Any,
    ) -> None:
        self._platform = str(platform).strip().lower()
        self._client_cls = client_cls
        self._root_config = config
        self._relational_storage_gateway = relational_storage_gateway
        self._logging_gateway = logging_gateway
        self._client_kwargs = dict(client_kwargs)
        self._lock = asyncio.Lock()
        self._initialized = False
        self._clients: dict[str, Any] = {}
        self._profile_snapshots: dict[str, dict[str, Any]] = {}
        self._client_profile_service = None
        if relational_storage_gateway is not None:
            self._client_profile_service = _messaging_client_profile_service_class()(
                table="admin_messaging_client_profile",
                rsg=relational_storage_gateway,
            )

    def configured_client_profile_ids(self) -> tuple[str, ...]:
        """List configured client profile ids for the current platform."""
        return tuple(self._clients.keys())

    async def _build_profile_clients(
        self,
        config: Mapping[str, Any] | SimpleNamespace,
    ) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        clients: dict[str, Any] = {}
        snapshots: dict[str, dict[str, Any]] = {}
        if self._client_profile_service is None:
            return clients, snapshots

        specs = await self._client_profile_service.list_active_runtime_specs(
            config=config,
            platform_key=self._platform,
        )
        for spec in specs:
            client_profile_id = str(spec.client_profile_id)
            clients[client_profile_id] = self._client_cls(
                config=spec.config,
                **self._client_kwargs,
            )
            snapshots[client_profile_id] = dict(spec.snapshot)
        return clients, snapshots

    async def _init_client_map(self, clients: Mapping[str, Any]) -> None:
        if not clients:
            return
        await asyncio.gather(
            *(client.init() for client in clients.values()),
            return_exceptions=False,
        )

    async def _verify_client_map(self, clients: Mapping[str, Any]) -> bool:
        if not clients:
            return True
        results = await asyncio.gather(
            *(client.verify_startup() for client in clients.values()),
            return_exceptions=False,
        )
        return all(result is True for result in results)

    async def _close_client_map(self, clients: Mapping[str, Any]) -> None:
        await _close_clients_fail_closed(
            platform=self._platform,
            clients=clients,
        )

    def _resolve_client_profile_id(
        self,
        client_profile_id: uuid.UUID | str | None = None,
    ) -> str:
        requested_id = normalize_client_profile_id(client_profile_id)
        if requested_id is None:
            requested_id = get_active_client_profile_id()
        if requested_id is not None:
            normalized_requested_id = str(requested_id)
            if normalized_requested_id not in self._clients:
                raise RuntimeError(
                    f"Unknown client profile id for {self._platform}: "
                    f"{normalized_requested_id!r}."
                )
            return normalized_requested_id

        configured = tuple(self._clients.keys())
        if len(configured) == 1:
            return configured[0]
        if not configured:
            raise RuntimeError(
                f"No active client profiles configured for platform {self._platform!r}."
            )
        raise RuntimeError(
            f"client_profile_id is required for multi-profile {self._platform} "
            "operations."
        )

    def _client_for(self, client_profile_id: uuid.UUID | str | None = None) -> Any:
        return self._clients[self._resolve_client_profile_id(client_profile_id)]

    async def init(self) -> None:
        async with self._lock:
            if self._initialized:
                return
            next_clients, next_snapshots = await self._build_profile_clients(
                self._root_config
            )
            await self._init_client_map(next_clients)
            self._clients = next_clients
            self._profile_snapshots = next_snapshots
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
        next_clients, next_snapshots = await self._build_profile_clients(next_config)

        try:
            await self._init_client_map(next_clients)
            verified = await self._verify_client_map(next_clients)
            if verified is not True:
                raise RuntimeError(
                    f"{self._platform} client profile startup probe failed."
                )
        except Exception as exc:
            try:
                await self._close_client_map(next_clients)
            except MultiProfileClientCloseError as close_exc:
                raise RuntimeError(
                    f"{self._platform} client profile reload failed after "
                    f"{type(exc).__name__}: {exc}; cleanup failed: {close_exc}"
                ) from close_exc
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

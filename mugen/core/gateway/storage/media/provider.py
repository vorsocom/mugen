"""Config-driven media storage gateway provider for web runtime."""

from __future__ import annotations

import os
from types import SimpleNamespace

from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.gateway.storage.media import IMediaStorageGateway
from mugen.core.gateway.storage.media.filesystem import FilesystemMediaStorageGateway
from mugen.core.gateway.storage.media.object import ObjectMediaStorageGateway


class DefaultMediaStorageGateway(IMediaStorageGateway):
    """Config-driven media gateway that delegates to a concrete backend."""

    _default_media_backend: str = "object"
    _default_media_storage_path: str = "data/web_media"
    _default_media_object_cache_path: str = "data/web_media_object_cache"

    def __init__(
        self,
        config: SimpleNamespace,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._config = config
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._backend = self._build_backend()

    async def check_readiness(self) -> None:
        await self._backend.check_readiness()

    async def init(self) -> None:
        await self._backend.init()

    async def close(self) -> None:
        await self._backend.close()

    async def store_bytes(
        self,
        payload: bytes,
        *,
        filename_hint: str | None = None,
    ) -> str | None:
        return await self._backend.store_bytes(payload, filename_hint=filename_hint)

    async def store_file(
        self,
        file_path: str,
        *,
        filename_hint: str | None = None,
    ) -> str | None:
        return await self._backend.store_file(file_path, filename_hint=filename_hint)

    async def exists(self, media_ref: str) -> bool:
        return await self._backend.exists(media_ref)

    async def materialize(self, media_ref: str) -> str | None:
        return await self._backend.materialize(media_ref)

    async def cleanup(
        self,
        *,
        active_refs: set[str],
        retention_seconds: int,
        now_epoch: float,
    ) -> None:
        await self._backend.cleanup(
            active_refs=active_refs,
            retention_seconds=retention_seconds,
            now_epoch=now_epoch,
        )

    def _build_backend(self) -> IMediaStorageGateway:
        backend = self._resolve_str_config(
            ("web", "media", "backend"),
            self._default_media_backend,
        ).strip().lower()

        if backend in {"filesystem", "fs", "local"}:
            if self._is_production_environment():
                raise RuntimeError(
                    "web.media.backend=filesystem is not allowed in production. "
                    "Use object backend."
                )
            storage_path = self._resolve_str_config(
                ("web", "media", "storage", "path"),
                self._default_media_storage_path,
            )
            return FilesystemMediaStorageGateway(
                base_path=self._resolve_storage_path(storage_path)
            )

        if backend in {"object", "object_storage", "keyval"}:
            raw_cache_path = self._resolve_str_config(
                ("web", "media", "object", "cache_path"),
                self._default_media_object_cache_path,
            )
            raw_key_prefix = self._resolve_str_config(
                ("web", "media", "object", "key_prefix"),
                "web:media:object",
            )
            return ObjectMediaStorageGateway(
                keyval_storage_gateway=self._keyval_storage_gateway,
                cache_path=self._resolve_storage_path(raw_cache_path),
                key_prefix=raw_key_prefix,
            )

        raise ValueError("web.media.backend must be one of: filesystem, object.")

    def _is_production_environment(self) -> bool:
        environment = str(
            getattr(getattr(self._config, "mugen", SimpleNamespace()), "environment", "")
            or ""
        ).strip().lower()
        return environment == "production"

    def _resolve_storage_path(self, configured_path: str) -> str:
        if os.path.isabs(configured_path):
            return configured_path

        basedir = getattr(self._config, "basedir", None)
        if isinstance(basedir, str) and basedir != "":
            return os.path.abspath(os.path.join(basedir, configured_path))

        return os.path.abspath(configured_path)

    def _resolve_str_config(
        self,
        path: tuple[str, ...],
        default: str,
    ) -> str:
        raw_value = self._resolve_config_path(path)
        if not isinstance(raw_value, str) or raw_value.strip() == "":
            return default
        return raw_value.strip()

    def _resolve_config_path(self, path: tuple[str, ...]):
        node = self._config
        for item in path:
            node = getattr(node, item, None)
            if node is None:
                return None
        return node

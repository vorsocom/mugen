"""Object-like media storage gateway backed by key-value storage."""

from __future__ import annotations

import asyncio
import glob
import os
from pathlib import Path
from time import time
from typing import Any
import uuid

from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.gateway.storage.media import IMediaStorageGateway


class ObjectMediaStorageGateway(IMediaStorageGateway):
    """Store media payloads as object blobs in key-value storage."""

    _ref_prefix = "object:"

    def __init__(
        self,
        *,
        keyval_storage_gateway: IKeyValStorageGateway,
        cache_path: str,
        key_prefix: str = "web:media:object",
    ) -> None:
        self._keyval_storage_gateway = keyval_storage_gateway
        self._cache_path = Path(cache_path).resolve()
        self._key_prefix = key_prefix.strip() or "web:media:object"

    async def init(self) -> None:
        await asyncio.to_thread(
            self._cache_path.mkdir,
            parents=True,
            exist_ok=True,
        )

    async def close(self) -> None:
        return None

    async def store_bytes(
        self,
        payload: bytes,
        *,
        filename_hint: str | None = None,
    ) -> str | None:
        if not isinstance(payload, bytes):
            return None

        object_id = uuid.uuid4().hex
        extension = self._infer_extension(filename_hint)
        blob_key = self._blob_key(object_id)

        await self._keyval_storage_gateway.put_bytes(
            blob_key,
            payload,
        )
        try:
            await self._keyval_storage_gateway.put_json(
                self._meta_key(object_id),
                {
                    "created_at": self._epoch_now(),
                    "extension": extension,
                },
            )
        except Exception:  # pylint: disable=broad-exception-caught
            try:
                await self._keyval_storage_gateway.delete(blob_key)
            except Exception:  # pylint: disable=broad-exception-caught
                ...
            raise

        return self._make_ref(object_id)

    async def store_file(
        self,
        file_path: str,
        *,
        filename_hint: str | None = None,
    ) -> str | None:
        if not isinstance(file_path, str) or file_path.strip() == "":
            return None

        path = Path(file_path).expanduser().resolve()
        if path.exists() is not True or path.is_file() is not True:
            return None

        try:
            payload = await asyncio.to_thread(path.read_bytes)
        except OSError:
            return None

        return await self.store_bytes(
            payload,
            filename_hint=filename_hint or path.name,
        )

    async def exists(self, media_ref: str) -> bool:
        object_id = self._parse_ref(media_ref)
        if object_id is None:
            return False
        return await self._keyval_storage_gateway.exists(self._blob_key(object_id))

    async def materialize(self, media_ref: str) -> str | None:
        object_id = self._parse_ref(media_ref)
        if object_id is None:
            return None

        blob = await self._keyval_storage_gateway.get_entry(self._blob_key(object_id))
        if blob is None:
            return None

        meta = await self._keyval_storage_gateway.get_json(self._meta_key(object_id))
        extension = ""
        if isinstance(meta, dict):
            extension = self._infer_extension(meta.get("extension"))

        cache_target = self._cache_path / f"{object_id}{extension}"

        def _write() -> None:
            cache_target.parent.mkdir(parents=True, exist_ok=True)
            cache_target.write_bytes(blob.payload)

        try:
            await asyncio.to_thread(_write)
        except OSError:
            return None

        return str(cache_target.resolve())

    async def cleanup(
        self,
        *,
        active_refs: set[str],
        retention_seconds: int,
        now_epoch: float,
    ) -> None:
        active_ids = {
            object_id
            for object_id in (self._parse_ref(value) for value in active_refs)
            if object_id is not None
        }

        cursor: str | None = None
        while True:
            page = await self._keyval_storage_gateway.list_keys(
                prefix=self._meta_key_prefix,
                limit=500,
                cursor=cursor,
            )
            for key in page.keys:
                object_id = self._meta_key_to_object_id(key)
                if object_id is None:
                    continue
                if object_id in active_ids:
                    continue

                try:
                    metadata = await self._keyval_storage_gateway.get_json(key)
                except Exception:  # pylint: disable=broad-exception-caught
                    metadata = None
                created_at = self._coerce_float(
                    metadata.get("created_at") if isinstance(metadata, dict) else None
                )
                if created_at is not None:
                    age_seconds = float(now_epoch - created_at)
                    if age_seconds < float(retention_seconds):
                        continue

                await self._delete_object(object_id)

            if page.next_cursor in [None, ""]:
                break
            if page.next_cursor == cursor:
                break
            cursor = page.next_cursor

    async def _delete_object(self, object_id: str) -> None:
        await self._keyval_storage_gateway.delete(self._blob_key(object_id))
        await self._keyval_storage_gateway.delete(self._meta_key(object_id))

        pattern = str((self._cache_path / f"{object_id}*").resolve())
        for candidate in glob.glob(pattern):
            try:
                await asyncio.to_thread(os.remove, candidate)
            except OSError:
                ...

    @property
    def _meta_key_prefix(self) -> str:
        return f"{self._key_prefix}:meta:"

    def _blob_key(self, object_id: str) -> str:
        return f"{self._key_prefix}:blob:{object_id}"

    def _meta_key(self, object_id: str) -> str:
        return f"{self._key_prefix}:meta:{object_id}"

    def _make_ref(self, object_id: str) -> str:
        return f"{self._ref_prefix}{object_id}"

    def _parse_ref(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized.startswith(self._ref_prefix):
            return None
        object_id = normalized[len(self._ref_prefix) :]
        if object_id == "":
            return None
        return object_id

    def _meta_key_to_object_id(self, key: str) -> str | None:
        if not isinstance(key, str) or not key.startswith(self._meta_key_prefix):
            return None
        object_id = key[len(self._meta_key_prefix) :]
        if object_id == "":
            return None
        return object_id

    @staticmethod
    def _infer_extension(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        suffix = Path(value).suffix.lower()
        if suffix == "" or len(suffix) > 16:
            return ""
        return suffix

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _epoch_now() -> float:
        return time()

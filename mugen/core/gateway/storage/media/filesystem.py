"""Filesystem-backed media storage gateway."""

from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
from typing import Any
import uuid

from mugen.core.contract.gateway.storage.media import IMediaStorageGateway


class FilesystemMediaStorageGateway(IMediaStorageGateway):
    """Persist media content directly on local filesystem."""

    def __init__(
        self,
        *,
        base_path: str,
    ) -> None:
        self._base_path = Path(base_path).resolve()

    async def init(self) -> None:
        await asyncio.to_thread(
            self._base_path.mkdir,
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

        extension = self._infer_extension(filename_hint)
        target = self._base_path / f"{uuid.uuid4().hex}{extension}"

        def _write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)

        try:
            await asyncio.to_thread(_write)
        except OSError:
            return None

        return str(target.resolve())

    async def store_file(
        self,
        file_path: str,
        *,
        filename_hint: str | None = None,
    ) -> str | None:
        if not isinstance(file_path, str) or file_path.strip() == "":
            return None

        source = Path(file_path).expanduser().resolve()
        if source.exists() is not True or source.is_file() is not True:
            return None

        try:
            source.relative_to(self._base_path)
            return str(source)
        except ValueError:
            ...

        extension = self._infer_extension(filename_hint) or source.suffix
        if len(extension) > 16:
            extension = ""
        target = self._base_path / f"{uuid.uuid4().hex}{extension}"

        def _copy() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        try:
            await asyncio.to_thread(_copy)
        except OSError:
            return None

        return str(target.resolve())

    async def exists(self, media_ref: str) -> bool:
        if not isinstance(media_ref, str) or media_ref.strip() == "":
            return False
        path = Path(media_ref).expanduser().resolve()
        return path.exists() and path.is_file()

    async def materialize(self, media_ref: str) -> str | None:
        if await self.exists(media_ref) is not True:
            return None
        return str(Path(media_ref).expanduser().resolve())

    async def cleanup(
        self,
        *,
        active_refs: set[str],
        retention_seconds: int,
        now_epoch: float,
    ) -> None:
        active = {
            str(Path(item).expanduser().resolve())
            for item in active_refs
            if isinstance(item, str) and item.strip() != ""
        }
        try:
            candidates = await asyncio.to_thread(lambda: list(self._base_path.iterdir()))
        except OSError:
            return

        for candidate in candidates:
            if candidate.is_file() is not True:
                continue

            candidate_path = str(candidate.resolve())
            if candidate_path in active:
                continue

            try:
                age_seconds = float(now_epoch - candidate.stat().st_mtime)
            except OSError:
                continue

            if age_seconds < float(retention_seconds):
                continue

            try:
                await asyncio.to_thread(candidate.unlink)
            except OSError:
                ...

    @staticmethod
    def _infer_extension(value: Any) -> str:
        if not isinstance(value, str):
            return ""

        suffix = Path(value).suffix.lower()
        if suffix == "" or len(suffix) > 16:
            return ""
        return suffix

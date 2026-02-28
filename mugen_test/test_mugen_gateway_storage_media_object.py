"""Unit tests for object-style media storage gateway."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from mugen.core.contract.gateway.storage.keyval import KeyValEntry, KeyValListPage
from mugen.core.gateway.storage.media.object import ObjectMediaStorageGateway


class _FakeKeyValGateway:
    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def put_bytes(self, key: str, value: bytes, **_kwargs) -> KeyValEntry:
        self._store[key] = bytes(value)
        return KeyValEntry(
            namespace="default",
            key=key,
            payload=self._store[key],
            codec="bytes",
            row_version=1,
        )

    async def put_json(self, key: str, value, **_kwargs) -> KeyValEntry:
        import json

        payload = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode(
            "utf-8"
        )
        self._store[key] = payload
        return KeyValEntry(
            namespace="default",
            key=key,
            payload=payload,
            codec="application/json",
            row_version=1,
        )

    async def get_entry(self, key: str, **_kwargs) -> KeyValEntry | None:
        payload = self._store.get(key)
        if payload is None:
            return None
        return KeyValEntry(
            namespace="default",
            key=key,
            payload=payload,
            codec="bytes",
            row_version=1,
        )

    async def get_json(self, key: str, **_kwargs):
        import json

        payload = self._store.get(key)
        if payload is None:
            return None
        return json.loads(payload.decode("utf-8"))

    async def exists(self, key: str, **_kwargs) -> bool:
        return key in self._store

    async def list_keys(
        self,
        *,
        prefix: str = "",
        limit: int | None = None,
        cursor: str | None = None,
        **_kwargs,
    ) -> KeyValListPage:
        keys = sorted(key for key in self._store if key.startswith(prefix))
        start_index = 0
        if cursor not in [None, ""]:
            for index, key in enumerate(keys):
                if key > str(cursor):
                    start_index = index
                    break
            else:
                return KeyValListPage(keys=[], next_cursor=None)

        page_limit = int(limit or len(keys) or 1)
        page = keys[start_index : start_index + page_limit]
        next_cursor = None
        if start_index + page_limit < len(keys) and page:
            next_cursor = page[-1]
        return KeyValListPage(keys=page, next_cursor=next_cursor)

    async def delete(self, key: str, **_kwargs):
        self._store.pop(key, None)
        return None


class TestObjectMediaStorageGateway(unittest.IsolatedAsyncioTestCase):
    """Covers keyval-backed object media persistence behavior."""

    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.keyval = _FakeKeyValGateway()
        self.gateway = ObjectMediaStorageGateway(
            keyval_storage_gateway=self.keyval,
            cache_path=os.path.join(self.tmpdir.name, "cache"),
        )
        await self.gateway.init()

    async def asyncTearDown(self) -> None:
        await self.gateway.close()
        self.tmpdir.cleanup()

    async def test_store_and_materialize(self) -> None:
        self.assertIsNone(await self.gateway.store_bytes("bad"))  # type: ignore[arg-type]
        media_ref = await self.gateway.store_bytes(b"payload", filename_hint="x.bin")
        self.assertTrue(media_ref.startswith("object:"))
        self.assertTrue(await self.gateway.exists(media_ref))

        materialized = await self.gateway.materialize(media_ref)
        self.assertIsInstance(materialized, str)
        self.assertEqual(Path(materialized).read_bytes(), b"payload")

        self.assertFalse(await self.gateway.exists("bad-ref"))
        self.assertIsNone(await self.gateway.materialize("bad-ref"))
        self.assertIsNone(
            self.gateway._meta_key_to_object_id("bad")  # pylint: disable=protected-access
        )
        self.assertEqual(
            self.gateway._infer_extension("name.12345678901234567"),  # pylint: disable=protected-access
            "",
        )
        self.assertIsNone(self.gateway._parse_ref(None))  # pylint: disable=protected-access
        self.assertIsNone(self.gateway._parse_ref("object:"))  # pylint: disable=protected-access
        self.assertIsNone(
            self.gateway._meta_key_to_object_id(  # pylint: disable=protected-access
                "web:media:object:meta:"
            )
        )

    async def test_store_bytes_rolls_back_blob_when_meta_write_fails(self) -> None:
        original_put_bytes = self.keyval.put_bytes
        original_delete = self.keyval.delete
        self.keyval.put_bytes = AsyncMock(side_effect=original_put_bytes)
        self.keyval.put_json = AsyncMock(side_effect=RuntimeError("meta write failed"))
        self.keyval.delete = AsyncMock(side_effect=original_delete)

        with self.assertRaisesRegex(RuntimeError, "meta write failed"):
            await self.gateway.store_bytes(b"payload", filename_hint="x.bin")

        blob_key = self.keyval.put_bytes.await_args.args[0]
        self.keyval.delete.assert_awaited_once_with(blob_key)
        self.assertNotIn(blob_key, self.keyval._store)

    async def test_store_bytes_raises_primary_error_when_rollback_delete_fails(self) -> None:
        original_put_json = self.keyval.put_json

        async def _put_json_once_then_write(key: str, value, **kwargs):
            _put_json_once_then_write.calls += 1
            if _put_json_once_then_write.calls == 1:
                raise RuntimeError("meta write failed")
            return await original_put_json(key, value, **kwargs)

        _put_json_once_then_write.calls = 0
        self.keyval.put_json = AsyncMock(side_effect=_put_json_once_then_write)
        self.keyval.put_bytes = AsyncMock(side_effect=self.keyval.put_bytes)
        self.keyval.delete = AsyncMock(side_effect=RuntimeError("rollback failed"))

        with self.assertRaisesRegex(RuntimeError, "meta write failed"):
            await self.gateway.store_bytes(b"payload", filename_hint="x.bin")

        self.keyval.delete.assert_awaited_once()
        blob_key = self.keyval.put_bytes.await_args.args[0]
        object_id = blob_key.rsplit(":", 1)[1]
        orphan_key = self.gateway._orphan_key(object_id)  # pylint: disable=protected-access
        self.assertIn(orphan_key, self.keyval._store)

    async def test_store_file_and_cleanup(self) -> None:
        source = os.path.join(self.tmpdir.name, "src.bin")
        with open(source, "wb") as handle:
            handle.write(b"source")

        stored_ref = await self.gateway.store_file(source)
        self.assertIsInstance(stored_ref, str)
        self.assertIsNone(await self.gateway.store_file(""))
        self.assertIsNone(await self.gateway.store_file("/missing"))

        keep_ref = await self.gateway.store_bytes(b"keep", filename_hint="keep.bin")
        stale_ref = await self.gateway.store_bytes(b"stale", filename_hint="stale.bin")

        stale_id = stale_ref.split(":", 1)[1]
        await self.keyval.put_json(
            self.gateway._meta_key(stale_id),  # pylint: disable=protected-access
            {"created_at": 1.0, "extension": ".bin"},
        )

        await self.gateway.cleanup(
            active_refs={keep_ref},
            retention_seconds=10,
            now_epoch=100.0,
        )

        self.assertFalse(await self.gateway.exists(stale_ref))
        self.assertTrue(await self.gateway.exists(keep_ref))
        self.assertTrue(await self.gateway.exists(stored_ref))

    async def test_store_file_and_materialize_failures(self) -> None:
        source = os.path.join(self.tmpdir.name, "src-fail.bin")
        with open(source, "wb") as handle:
            handle.write(b"source")

        with patch("pathlib.Path.read_bytes", side_effect=OSError()):
            self.assertIsNone(await self.gateway.store_file(source))

        media_ref = await self.gateway.store_bytes(b"payload")
        object_id = media_ref.split(":", 1)[1]
        await self.keyval.delete(self.gateway._blob_key(object_id))  # pylint: disable=protected-access
        self.assertIsNone(await self.gateway.materialize(media_ref))

        media_ref = await self.gateway.store_bytes(b"payload")
        object_id = media_ref.split(":", 1)[1]
        await self.keyval.put_json(
            self.gateway._meta_key(object_id),  # pylint: disable=protected-access
            ["not", "a", "dict"],
        )
        with patch("pathlib.Path.write_bytes", side_effect=OSError()):
            self.assertIsNone(await self.gateway.materialize(media_ref))

    async def test_cleanup_handles_invalid_metadata(self) -> None:
        media_ref = await self.gateway.store_bytes(b"payload")
        object_id = media_ref.split(":", 1)[1]
        await self.keyval.put_bytes(
            self.gateway._meta_key(object_id),  # pylint: disable=protected-access
            b"not-json",
        )
        await self.gateway.cleanup(
            active_refs=set(),
            retention_seconds=0,
            now_epoch=100.0,
        )
        self.assertFalse(await self.gateway.exists(media_ref))

    async def test_cleanup_cursor_cycle_and_remove_error(self) -> None:
        media_ref = await self.gateway.store_bytes(b"payload")
        object_id = media_ref.split(":", 1)[1]
        cache_file = Path(self.tmpdir.name) / "cache" / f"{object_id}.bin"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(b"cached")

        await self.keyval.put_json(
            self.gateway._meta_key(object_id),  # pylint: disable=protected-access
            {"created_at": 0.0, "extension": ".bin"},
        )
        await self.keyval.put_json(
            "web:media:object:meta:",
            {"created_at": 0.0, "extension": ".bin"},
        )

        self.keyval.list_keys = AsyncMock(
            side_effect=[
                KeyValListPage(keys=[], next_cursor=None),
                KeyValListPage(
                    keys=[
                        "web:media:object:meta:",
                        self.gateway._meta_key(object_id),  # pylint: disable=protected-access
                    ],
                    next_cursor="same",
                ),
                KeyValListPage(keys=[], next_cursor="same"),
            ]
        )
        with patch("os.remove", side_effect=OSError()):
            await self.gateway.cleanup(
                active_refs=set(),
                retention_seconds=0,
                now_epoch=100.0,
            )

    async def test_cleanup_retries_orphan_markers_until_delete_succeeds(self) -> None:
        orphan_key = self.gateway._orphan_key("orphan-1")  # pylint: disable=protected-access
        await self.keyval.put_json(
            orphan_key,
            {
                "object_id": "orphan-1",
                "created_at": 1.0,
                "reason": "metadata_write_failed:RuntimeError",
            },
        )

        with patch.object(
            self.gateway,
            "_delete_object",
            new=AsyncMock(side_effect=[RuntimeError("backend down"), None]),
        ):
            await self.gateway.cleanup(
                active_refs=set(),
                retention_seconds=0,
                now_epoch=100.0,
            )
            self.assertIn(orphan_key, self.keyval._store)

            await self.gateway.cleanup(
                active_refs=set(),
                retention_seconds=0,
                now_epoch=100.0,
            )
            self.assertNotIn(orphan_key, self.keyval._store)

    async def test_cleanup_orphan_markers_handles_invalid_keys_and_cursor_cycles(self) -> None:
        self.keyval.list_keys = AsyncMock(
            side_effect=[
                KeyValListPage(
                    keys=[
                        "not-an-orphan-key",
                        self.gateway._orphan_key_prefix,  # pylint: disable=protected-access
                    ],
                    next_cursor="same",
                ),
                KeyValListPage(keys=[], next_cursor="same"),
                KeyValListPage(keys=[], next_cursor=None),
            ]
        )
        await self.gateway.cleanup(
            active_refs=set(),
            retention_seconds=0,
            now_epoch=100.0,
        )

    async def test_cleanup_orphan_marker_delete_failure_is_logged_and_marker_is_retained(
        self,
    ) -> None:
        orphan_key = self.gateway._orphan_key("orphan-delete-fail")  # pylint: disable=protected-access
        await self.keyval.put_json(
            orphan_key,
            {
                "object_id": "orphan-delete-fail",
                "created_at": 1.0,
                "reason": "metadata_write_failed:RuntimeError",
            },
        )
        self.keyval.delete = AsyncMock(side_effect=RuntimeError("marker delete failed"))

        with patch.object(
            self.gateway,
            "_delete_object",
            new=AsyncMock(return_value=None),
        ):
            await self.gateway.cleanup(
                active_refs=set(),
                retention_seconds=0,
                now_epoch=100.0,
            )

        self.assertIn(orphan_key, self.keyval._store)

    async def test_orphan_key_parser_rejects_invalid_and_empty_values(self) -> None:
        self.assertIsNone(
            self.gateway._orphan_key_to_object_id("bad")  # pylint: disable=protected-access
        )
        self.assertIsNone(
            self.gateway._orphan_key_to_object_id(  # pylint: disable=protected-access
                self.gateway._orphan_key_prefix  # pylint: disable=protected-access
            )
        )

    async def test_record_orphan_marker_logs_when_write_fails(self) -> None:
        self.keyval.put_json = AsyncMock(side_effect=RuntimeError("marker write failed"))

        with self.assertLogs(
            "mugen.core.gateway.storage.media.object",
            level="WARNING",
        ) as logs:
            await self.gateway._record_orphan_marker(  # pylint: disable=protected-access
                object_id="orphan-write-fail",
                reason="metadata_write_failed:RuntimeError",
            )

        self.assertTrue(any("orphan marker write failed" in msg for msg in logs.output))


if __name__ == "__main__":
    unittest.main()

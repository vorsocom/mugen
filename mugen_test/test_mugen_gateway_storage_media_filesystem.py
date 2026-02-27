"""Unit tests for filesystem media storage gateway."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from mugen.core.gateway.storage.media.filesystem import FilesystemMediaStorageGateway


class TestFilesystemMediaStorageGateway(unittest.IsolatedAsyncioTestCase):
    """Covers filesystem media persistence behavior."""

    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base_path = os.path.join(self.tmpdir.name, "media")
        self.gateway = FilesystemMediaStorageGateway(base_path=self.base_path)
        await self.gateway.init()

    async def asyncTearDown(self) -> None:
        await self.gateway.close()
        self.tmpdir.cleanup()

    async def test_store_bytes_and_materialize(self) -> None:
        self.assertIsNone(await self.gateway.store_bytes("bad"))  # type: ignore[arg-type]

        media_ref = await self.gateway.store_bytes(b"payload", filename_hint="x.bin")
        self.assertIsInstance(media_ref, str)
        self.assertTrue(await self.gateway.exists(media_ref))
        self.assertEqual(await self.gateway.materialize(media_ref), media_ref)
        self.assertIsNone(await self.gateway.materialize(""))
        self.assertFalse(await self.gateway.exists("/etc/passwd"))
        self.assertIsNone(await self.gateway.materialize("/etc/passwd"))

    async def test_store_file_and_cleanup(self) -> None:
        outside_path = os.path.join(self.tmpdir.name, "outside.bin")
        with open(outside_path, "wb") as handle:
            handle.write(b"outside")

        stored_ref = await self.gateway.store_file(outside_path)
        self.assertIsInstance(stored_ref, str)
        self.assertNotEqual(os.path.abspath(outside_path), stored_ref)

        self.assertIsNone(await self.gateway.store_file(""))
        self.assertIsNone(await self.gateway.store_file("/not-found"))

        in_base = os.path.join(self.base_path, "already.bin")
        with open(in_base, "wb") as handle:
            handle.write(b"x")
        self.assertEqual(await self.gateway.store_file(in_base), os.path.abspath(in_base))

        stale_file = Path(self.base_path) / "stale.bin"
        stale_file.write_bytes(b"stale")
        os.utime(stale_file, (1, 1))

        active_file = Path(self.base_path) / "active.bin"
        active_file.write_bytes(b"active")
        os.utime(active_file, (1, 1))

        fresh_file = Path(self.base_path) / "fresh.bin"
        fresh_file.write_bytes(b"fresh")

        await self.gateway.cleanup(
            active_refs={str(active_file.resolve())},
            retention_seconds=10,
            now_epoch=100.0,
        )

        self.assertFalse(stale_file.exists())
        self.assertTrue(active_file.exists())
        self.assertTrue(fresh_file.exists())

    async def test_store_write_and_copy_failures(self) -> None:
        with patch("pathlib.Path.write_bytes", side_effect=OSError()):
            self.assertIsNone(await self.gateway.store_bytes(b"payload"))

        source = os.path.join(self.tmpdir.name, "source.12345678901234567")
        with open(source, "wb") as handle:
            handle.write(b"x")
        with patch("shutil.copy2", side_effect=OSError()):
            self.assertIsNone(await self.gateway.store_file(source))

    async def test_cleanup_stat_and_unlink_failures(self) -> None:
        class _StatFailCandidate:
            def is_file(self):
                return True

            def resolve(self):
                return Path(self_path)

            def stat(self):
                raise OSError()

            def unlink(self):
                return None

        self_path = os.path.join(self.tmpdir.name, "stat-fail.bin")
        with patch(
            "mugen.core.gateway.storage.media.filesystem.asyncio.to_thread",
            AsyncMock(return_value=[_StatFailCandidate()]),
        ):
            await self.gateway.cleanup(
                active_refs=set(),
                retention_seconds=0,
                now_epoch=100.0,
            )

        class _UnlinkFailCandidate:
            def is_file(self):
                return True

            def resolve(self):
                return Path(unlink_path)

            class _StatResult:
                st_mtime = 0.0

            def stat(self):
                return self._StatResult()

            def unlink(self):
                raise OSError()

        unlink_path = os.path.join(self.tmpdir.name, "unlink-fail.bin")
        with patch(
            "mugen.core.gateway.storage.media.filesystem.asyncio.to_thread",
            AsyncMock(
                side_effect=[
                    [_UnlinkFailCandidate()],
                    OSError(),
                ]
            ),
        ):
            await self.gateway.cleanup(
                active_refs=set(),
                retention_seconds=1,
                now_epoch=100.0,
            )

    async def test_infer_extension_and_non_file_candidates(self) -> None:
        self.assertEqual(self.gateway._infer_extension(None), "")  # pylint: disable=protected-access
        self.assertEqual(
            self.gateway._infer_extension("name.12345678901234567"),  # pylint: disable=protected-access
            "",
        )

        nested_dir = Path(self.base_path) / "nested"
        nested_dir.mkdir(parents=True, exist_ok=True)
        await self.gateway.cleanup(
            active_refs=set(),
            retention_seconds=0,
            now_epoch=100.0,
        )
        self.assertTrue(nested_dir.exists())

    async def test_exists_blocks_symlink_escape_and_traversal_paths(self) -> None:
        outside_path = os.path.join(self.tmpdir.name, "outside-secret.txt")
        with open(outside_path, "w", encoding="utf-8") as handle:
            handle.write("secret")

        symlink_path = os.path.join(self.base_path, "escape-link.txt")
        os.symlink(outside_path, symlink_path)
        self.assertFalse(await self.gateway.exists(symlink_path))
        self.assertIsNone(await self.gateway.materialize(symlink_path))

        traversal_ref = os.path.join(self.base_path, "..", "outside-secret.txt")
        self.assertFalse(await self.gateway.exists(traversal_ref))
        self.assertIsNone(await self.gateway.materialize(traversal_ref))

    async def test_exists_and_materialize_handle_path_resolution_oserror(self) -> None:
        with patch("pathlib.Path.resolve", side_effect=OSError()):
            self.assertFalse(await self.gateway.exists("local.bin"))
            self.assertIsNone(await self.gateway.materialize("local.bin"))


if __name__ == "__main__":
    unittest.main()

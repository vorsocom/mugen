"""Regression tests for authorization revocation during streaming responses."""

import asyncio
from collections.abc import AsyncIterator
import unittest
from unittest.mock import AsyncMock

from mugen.core.plugin.acp.api.stream import authorized_stream


class TestAcpApiStream(unittest.IsolatedAsyncioTestCase):
    """Check output revocation and resource cleanup for live streams."""

    async def test_revocation_prevents_the_next_chunk_and_closes_source(self) -> None:
        for revoked_chunk in ("replay", "live", ": ping\n\n"):
            with self.subTest(revoked_chunk=revoked_chunk):
                closed = asyncio.Event()

                async def _source() -> AsyncIterator[str]:
                    try:
                        yield "allowed"
                        yield revoked_chunk
                        self.fail("Stream advanced after access was revoked.")
                    finally:
                        closed.set()

                permission = AsyncMock(side_effect=[True, False])
                stream = authorized_stream(_source(), permitted=permission)
                self.assertEqual([chunk async for chunk in stream], ["allowed"])
                self.assertEqual(permission.await_count, 2)
                self.assertTrue(closed.is_set())

    async def test_revalidation_failure_closes_source_without_emitting(self) -> None:
        closed = asyncio.Event()

        async def _source() -> AsyncIterator[str]:
            try:
                yield "sensitive"
            finally:
                closed.set()

        stream = authorized_stream(
            _source(),
            permitted=AsyncMock(side_effect=RuntimeError("authorization unavailable")),
        )
        with self.assertRaisesRegex(RuntimeError, "authorization unavailable"):
            await anext(stream)
        self.assertTrue(closed.is_set())

    async def test_consumer_disconnect_closes_source(self) -> None:
        closed = asyncio.Event()

        async def _source() -> AsyncIterator[str]:
            try:
                yield "first"
                yield "second"
            finally:
                closed.set()

        stream = authorized_stream(_source(), permitted=AsyncMock(return_value=True))
        self.assertEqual(await anext(stream), "first")
        await stream.aclose()
        self.assertTrue(closed.is_set())

    async def test_completed_iterator_without_close_is_supported(self) -> None:
        class _Source:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        permission = AsyncMock()
        stream = authorized_stream(_Source(), permitted=permission)
        self.assertEqual([chunk async for chunk in stream], [])
        permission.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

"""Unit tests for core Signal client contract defaults."""

import unittest

from mugen.core.contract.client.signal import ISignalClient


class _SignalClientPort(ISignalClient):
    async def init(self) -> None:
        return None

    async def verify_startup(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    async def receive_events(self):
        if False:
            yield {}
        return

    async def send_text_message(
        self,
        *,
        recipient: str,
        text: str,
    ) -> dict | None:
        _ = (recipient, text)
        return {"ok": True}

    async def send_media_message(
        self,
        *,
        recipient: str,
        message: str | None = None,
        base64_attachments: list[str] | None = None,
    ) -> dict | None:
        _ = (recipient, message, base64_attachments)
        return {"ok": True}

    async def send_reaction(
        self,
        *,
        recipient: str,
        reaction: str,
        target_author: str,
        timestamp: int,
        remove: bool = False,
    ) -> dict | None:
        _ = (recipient, reaction, target_author, timestamp, remove)
        return {"ok": True}

    async def send_receipt(
        self,
        *,
        recipient: str,
        receipt_type: str,
        timestamp: int,
    ) -> dict | None:
        _ = (recipient, receipt_type, timestamp)
        return {"ok": True}

    async def emit_processing_signal(
        self,
        recipient: str,
        *,
        state: str,
        message_id: str | None = None,
    ) -> bool | None:
        _ = (recipient, state, message_id)
        return True

    async def download_attachment(self, attachment_id: str) -> dict | None:
        _ = attachment_id
        return {"path": "/tmp/file.bin"}


class _IncompleteSignalClientPort(ISignalClient):
    async def init(self) -> None:
        return None


class TestMugenContractClientSignal(unittest.IsolatedAsyncioTestCase):
    """Validate required abstract methods on ISignalClient."""

    async def test_required_signal_methods_are_callable_on_complete_port(self) -> None:
        client = _SignalClientPort()

        self.assertTrue(await client.verify_startup())
        self.assertEqual(
            await client.send_text_message(recipient="+1", text="hello"),
            {"ok": True},
        )
        self.assertEqual(
            await client.download_attachment("att-1"),
            {"path": "/tmp/file.bin"},
        )

    async def test_incomplete_port_cannot_be_instantiated(self) -> None:
        with self.assertRaises(TypeError):
            _IncompleteSignalClientPort()

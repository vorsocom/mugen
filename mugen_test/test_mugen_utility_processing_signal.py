"""Unit tests for mugen.core.utility.processing_signal."""

import unittest

from mugen.core.utility.processing_signal import (
    PROCESSING_SIGNAL_THINKING,
    build_thinking_signal_payload,
    normalize_processing_state,
)


class TestMugenUtilityProcessingSignal(unittest.TestCase):
    """Covers processing signal validation and payload helpers."""

    def test_normalize_processing_state_accepts_supported_values(self) -> None:
        self.assertEqual(normalize_processing_state("start"), "start")
        self.assertEqual(normalize_processing_state(" STOP "), "stop")

    def test_normalize_processing_state_rejects_unsupported_values(self) -> None:
        with self.assertRaises(ValueError):
            normalize_processing_state("pause")

    def test_build_thinking_signal_payload(self) -> None:
        payload = build_thinking_signal_payload(
            state="start",
            job_id="job-1",
            conversation_id="conv-1",
            client_message_id="client-1",
            sender="user-1",
        )

        self.assertEqual(payload["signal"], PROCESSING_SIGNAL_THINKING)
        self.assertEqual(payload["state"], "start")
        self.assertEqual(payload["job_id"], "job-1")
        self.assertEqual(payload["conversation_id"], "conv-1")
        self.assertEqual(payload["client_message_id"], "client-1")
        self.assertEqual(payload["sender"], "user-1")

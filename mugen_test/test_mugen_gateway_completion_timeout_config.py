"""Unit tests for completion timeout helper functions."""

import unittest

from mugen.core.gateway.completion.timeout_config import to_timeout_milliseconds


class TestMugenGatewayCompletionTimeoutConfig(unittest.TestCase):
    """Covers edge cases for timeout conversion helpers."""

    def test_to_timeout_milliseconds_handles_none_and_sub_second_values(self) -> None:
        self.assertIsNone(to_timeout_milliseconds(None))
        self.assertEqual(to_timeout_milliseconds(0.001), 1)
        self.assertEqual(to_timeout_milliseconds(0.25), 250)


if __name__ == "__main__":
    unittest.main()

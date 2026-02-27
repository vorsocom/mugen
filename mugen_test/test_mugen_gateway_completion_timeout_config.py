"""Unit tests for completion timeout helper functions."""

import unittest

from mugen.core.gateway.completion.timeout_config import (
    parse_bool_like,
    to_timeout_milliseconds,
)


class TestMugenGatewayCompletionTimeoutConfig(unittest.TestCase):
    """Covers edge cases for timeout conversion helpers."""

    def test_to_timeout_milliseconds_handles_none_and_sub_second_values(self) -> None:
        self.assertIsNone(to_timeout_milliseconds(None))
        self.assertEqual(to_timeout_milliseconds(0.001), 1)
        self.assertEqual(to_timeout_milliseconds(0.25), 250)

    def test_parse_bool_like_accepts_bool_int_and_string_values(self) -> None:
        self.assertTrue(
            parse_bool_like(
                value=True,
                field_name="field",
                provider_label="Provider",
            )
        )
        self.assertFalse(
            parse_bool_like(
                value=False,
                field_name="field",
                provider_label="Provider",
            )
        )
        self.assertTrue(
            parse_bool_like(
                value=1,
                field_name="field",
                provider_label="Provider",
            )
        )
        self.assertFalse(
            parse_bool_like(
                value=0,
                field_name="field",
                provider_label="Provider",
            )
        )
        self.assertTrue(
            parse_bool_like(
                value=" yes ",
                field_name="field",
                provider_label="Provider",
            )
        )
        self.assertFalse(
            parse_bool_like(
                value="off",
                field_name="field",
                provider_label="Provider",
            )
        )

    def test_parse_bool_like_rejects_invalid_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid boolean value for field"):
            parse_bool_like(
                value=2,
                field_name="field",
                provider_label="Provider",
            )

        with self.assertRaisesRegex(ValueError, "Invalid boolean value for field"):
            parse_bool_like(
                value="maybe",
                field_name="field",
                provider_label="Provider",
            )

        with self.assertRaisesRegex(ValueError, "Invalid boolean value for field"):
            parse_bool_like(
                value=0.1,
                field_name="field",
                provider_label="Provider",
            )


if __name__ == "__main__":
    unittest.main()

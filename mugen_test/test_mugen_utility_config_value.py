"""Unit tests for strict config value parsers."""

from __future__ import annotations

import unittest

from mugen.core.utility.config_value import (
    parse_bool_flag,
    parse_nonnegative_finite_float,
    parse_optional_positive_finite_float,
    parse_optional_positive_int,
    parse_required_positive_finite_float,
    parse_required_positive_int,
)


class TestMugenUtilityConfigValue(unittest.TestCase):
    def test_parse_bool_flag(self) -> None:
        self.assertTrue(parse_bool_flag(True, default=False))
        self.assertFalse(parse_bool_flag(False, default=True))
        self.assertTrue(parse_bool_flag("yes", default=False))
        self.assertFalse(parse_bool_flag("off", default=True))
        self.assertTrue(parse_bool_flag(1, default=False))
        self.assertFalse(parse_bool_flag(0, default=True))
        self.assertTrue(parse_bool_flag("unknown", default=True))

    def test_parse_required_positive_finite_float(self) -> None:
        self.assertEqual(
            parse_required_positive_finite_float("2.5", "field"),
            2.5,
        )
        with self.assertRaisesRegex(RuntimeError, "field is required"):
            parse_required_positive_finite_float(None, "field")
        with self.assertRaisesRegex(RuntimeError, "positive finite number"):
            parse_required_positive_finite_float("bad", "field")
        with self.assertRaisesRegex(RuntimeError, "positive finite number"):
            parse_required_positive_finite_float(float("nan"), "field")
        with self.assertRaisesRegex(RuntimeError, "positive finite number"):
            parse_required_positive_finite_float(float("inf"), "field")
        with self.assertRaisesRegex(RuntimeError, "greater than 0"):
            parse_required_positive_finite_float(0, "field")

    def test_parse_optional_positive_finite_float(self) -> None:
        self.assertIsNone(parse_optional_positive_finite_float(None, "field"))
        self.assertEqual(parse_optional_positive_finite_float("2", "field"), 2.0)
        with self.assertRaisesRegex(RuntimeError, "positive finite number"):
            parse_optional_positive_finite_float("bad", "field")
        with self.assertRaisesRegex(RuntimeError, "positive finite number"):
            parse_optional_positive_finite_float(float("-inf"), "field")
        with self.assertRaisesRegex(RuntimeError, "greater than 0"):
            parse_optional_positive_finite_float(-1, "field")

    def test_parse_nonnegative_finite_float(self) -> None:
        self.assertEqual(
            parse_nonnegative_finite_float(None, "field", default=3.0),
            3.0,
        )
        self.assertEqual(
            parse_nonnegative_finite_float("1.5", "field", default=3.0),
            1.5,
        )
        with self.assertRaisesRegex(RuntimeError, "non-negative finite number"):
            parse_nonnegative_finite_float("bad", "field", default=3.0)
        with self.assertRaisesRegex(RuntimeError, "non-negative finite number"):
            parse_nonnegative_finite_float(float("nan"), "field", default=3.0)
        with self.assertRaisesRegex(RuntimeError, "greater than or equal to 0"):
            parse_nonnegative_finite_float(-0.1, "field", default=3.0)
        with self.assertRaisesRegex(RuntimeError, "default must be non-negative finite"):
            parse_nonnegative_finite_float(None, "field", default=float("inf"))

    def test_parse_required_positive_int(self) -> None:
        self.assertEqual(parse_required_positive_int("2", "field"), 2)
        with self.assertRaisesRegex(RuntimeError, "field is required"):
            parse_required_positive_int("", "field")
        with self.assertRaisesRegex(RuntimeError, "positive integer"):
            parse_required_positive_int("bad", "field")
        with self.assertRaisesRegex(RuntimeError, "positive integer"):
            parse_required_positive_int(True, "field")
        with self.assertRaisesRegex(RuntimeError, "greater than 0"):
            parse_required_positive_int(0, "field")

    def test_parse_optional_positive_int(self) -> None:
        self.assertIsNone(parse_optional_positive_int(None, "field"))
        self.assertEqual(parse_optional_positive_int("8", "field"), 8)
        with self.assertRaisesRegex(RuntimeError, "positive integer"):
            parse_optional_positive_int("bad", "field")
        with self.assertRaisesRegex(RuntimeError, "greater than 0"):
            parse_optional_positive_int(-1, "field")


if __name__ == "__main__":
    unittest.main()

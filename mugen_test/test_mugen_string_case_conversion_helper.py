"""Unit tests for string case conversion helpers."""

import unittest

from mugen.core.utility.string.case_conversion_helper import (
    snake_keys_to_title,
    snake_to_title,
    title_keys_to_snake,
    title_to_snake,
)


class TestMugenStringCaseConversionHelper(unittest.TestCase):
    """Tests string and recursive key conversion helpers."""

    def test_snake_to_title_handles_basic_and_empty_values(self) -> None:
        self.assertEqual(snake_to_title("user_id"), "UserId")
        self.assertEqual(snake_to_title(""), "")
        self.assertIsNone(snake_to_title(None))

    def test_title_to_snake_handles_basic_and_empty_values(self) -> None:
        self.assertEqual(title_to_snake("UserId"), "user_id")
        self.assertEqual(title_to_snake("IsActive"), "is_active")
        self.assertEqual(title_to_snake(""), "")
        self.assertIsNone(title_to_snake(None))

    def test_snake_keys_to_title_recurses_for_mappings_lists_and_tuples(self) -> None:
        payload = {
            "user_id": 1,
            "is_active": True,
            "nested_value": {"room_id": "abc"},
            "items": [{"item_id": 1}, {"item_id": 2}],
            "pairs": ({"entry_id": 3},),
        }

        converted = snake_keys_to_title(payload)

        self.assertEqual(converted["UserId"], 1)
        self.assertEqual(converted["IsActive"], True)
        self.assertEqual(converted["NestedValue"]["RoomId"], "abc")
        self.assertEqual(converted["Items"][0]["ItemId"], 1)
        self.assertEqual(converted["Pairs"][0]["EntryId"], 3)

    def test_title_keys_to_snake_recurses_for_mappings_lists_and_tuples(self) -> None:
        payload = {
            "UserId": 1,
            "IsActive": True,
            "NestedValue": {"RoomId": "abc"},
            "Items": [{"ItemId": 1}, {"ItemId": 2}],
            "Pairs": ({"EntryId": 3},),
        }

        converted = title_keys_to_snake(payload)

        self.assertEqual(converted["user_id"], 1)
        self.assertEqual(converted["is_active"], True)
        self.assertEqual(converted["nested_value"]["room_id"], "abc")
        self.assertEqual(converted["items"][0]["item_id"], 1)
        self.assertEqual(converted["pairs"][0]["entry_id"], 3)

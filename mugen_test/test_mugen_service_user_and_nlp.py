"""Unit tests for user and NLP service defaults."""

import unittest
from unittest.mock import AsyncMock, Mock
from unittest.mock import patch

from mugen.core.contract.gateway.storage.keyval_model import (
    KeyValConflictError,
    KeyValEntry,
)
from mugen.core.service.nlp import DefaultNLPService
from mugen.core.service.user import DefaultUserService


class TestMugenServiceUserAndNlp(unittest.IsolatedAsyncioTestCase):
    """Tests key-value backed user methods and NLP default behavior."""

    async def test_get_known_users_list_returns_empty_without_storage_key(self) -> None:
        keyval = Mock()
        keyval.get_json = AsyncMock(return_value=None)
        svc = DefaultUserService(
            keyval_storage_gateway=keyval,
            logging_gateway=Mock(),
        )

        self.assertEqual(await svc.get_known_users_list(), {})
        keyval.get_json.assert_called_once_with("known_users_list")

    async def test_get_known_users_list_deserializes_when_key_exists(self) -> None:
        payload = {"u1": {"displayname": "Alice", "dm_id": "!room"}}
        keyval = Mock()
        keyval.get_json = AsyncMock(return_value=payload)
        svc = DefaultUserService(
            keyval_storage_gateway=keyval,
            logging_gateway=Mock(),
        )

        self.assertEqual(await svc.get_known_users_list(), payload)

    async def test_get_known_users_list_invalid_payload_resets(self) -> None:
        keyval = Mock()
        keyval.get_json = AsyncMock(return_value=["not-a-dict"])
        logger = Mock()
        svc = DefaultUserService(
            keyval_storage_gateway=keyval,
            logging_gateway=logger,
        )

        self.assertEqual(await svc.get_known_users_list(), {})
        logger.warning.assert_called_once()

    async def test_add_known_user_and_display_name_paths(self) -> None:
        keyval = Mock()
        # First read for add, then read for display name lookup.
        keyval.get_entry = AsyncMock(side_effect=[None])
        keyval.put_json = AsyncMock()
        keyval.get_json = AsyncMock(
            return_value={"@alice": {"displayname": "Alice", "dm_id": "!dm"}}
        )
        svc = DefaultUserService(
            keyval_storage_gateway=keyval,
            logging_gateway=Mock(),
        )

        await svc.add_known_user(user_id="@alice", displayname="Alice", room_id="!dm")

        keyval.put_json.assert_called_once()
        self.assertEqual(keyval.put_json.call_args.kwargs["expected_row_version"], 0)
        stored_payload = keyval.put_json.call_args.args[1]
        self.assertEqual(stored_payload["@alice"]["displayname"], "Alice")
        self.assertEqual(stored_payload["@alice"]["dm_id"], "!dm")

        self.assertEqual(await svc.get_user_display_name("@alice"), "Alice")
        self.assertEqual(await svc.get_user_display_name("@missing"), "")

    async def test_save_known_users_list_serializes_payload(self) -> None:
        keyval = Mock()
        keyval.put_json = AsyncMock()
        svc = DefaultUserService(
            keyval_storage_gateway=keyval,
            logging_gateway=Mock(),
        )
        payload = {"u2": {"displayname": "Bob", "dm_id": "!room2"}}

        await svc.save_known_users_list(payload)

        keyval.put_json.assert_called_once_with("known_users_list", payload)

    async def test_add_known_user_logs_when_existing_payload_is_invalid(self) -> None:
        keyval = Mock()
        keyval.get_entry = AsyncMock(
            return_value=KeyValEntry(
                namespace="default",
                key="known_users_list",
                payload=b"not-json",
                codec="text/utf-8",
                row_version=3,
            )
        )
        keyval.put_json = AsyncMock()
        logger = Mock()
        svc = DefaultUserService(
            keyval_storage_gateway=keyval,
            logging_gateway=logger,
        )

        await svc.add_known_user(user_id="@bob", displayname="Bob", room_id="!dm2")

        logger.warning.assert_called_once_with("Invalid known users payload; resetting.")
        keyval.put_json.assert_awaited_once()
        self.assertEqual(keyval.put_json.call_args.kwargs["expected_row_version"], 3)

    async def test_add_known_user_conflict_retries_then_raises_conflict(self) -> None:
        keyval = Mock()
        existing_entry = KeyValEntry(
            namespace="default",
            key="known_users_list",
            payload=b'{"@existing":{"displayname":"Existing","dm_id":"!x"}}',
            codec="application/json",
            row_version=1,
        )
        keyval.get_entry = AsyncMock(side_effect=[existing_entry] * 5)
        keyval.get_json = AsyncMock(return_value={"@existing": {"displayname": "Existing"}})
        keyval.put_json = AsyncMock(
            side_effect=[
                KeyValConflictError(
                    namespace="default",
                    key="known_users_list",
                    expected_row_version=1,
                    current_row_version=2,
                ),
                KeyValConflictError(
                    namespace="default",
                    key="known_users_list",
                    expected_row_version=1,
                    current_row_version=2,
                ),
                KeyValConflictError(
                    namespace="default",
                    key="known_users_list",
                    expected_row_version=1,
                    current_row_version=2,
                ),
                KeyValConflictError(
                    namespace="default",
                    key="known_users_list",
                    expected_row_version=1,
                    current_row_version=2,
                ),
                KeyValConflictError(
                    namespace="default",
                    key="known_users_list",
                    expected_row_version=1,
                    current_row_version=2,
                ),
            ]
        )
        svc = DefaultUserService(
            keyval_storage_gateway=keyval,
            logging_gateway=Mock(),
        )

        with self.assertRaises(KeyValConflictError):
            await svc.add_known_user(user_id="@alice", displayname="Alice", room_id="!dm")
        self.assertEqual(keyval.put_json.await_count, 5)

    async def test_add_known_user_raises_runtime_error_when_retries_are_zero(self) -> None:
        keyval = Mock()
        svc = DefaultUserService(
            keyval_storage_gateway=keyval,
            logging_gateway=Mock(),
        )
        with patch.object(svc, "_default_cas_retries", 0):
            with self.assertRaises(RuntimeError):
                await svc.add_known_user(
                    user_id="@alice",
                    displayname="Alice",
                    room_id="!dm",
                )

    async def test_default_nlp_service_returns_empty_keywords(self) -> None:
        svc = DefaultNLPService(logging_gateway=Mock())
        self.assertEqual(svc.get_keywords("hello world"), [])

    async def test_get_user_display_name_ignores_non_string_display_name(self) -> None:
        keyval = Mock()
        keyval.get_json = AsyncMock(return_value={"u1": {"displayname": 123}})
        svc = DefaultUserService(
            keyval_storage_gateway=keyval,
            logging_gateway=Mock(),
        )
        self.assertEqual(await svc.get_user_display_name("u1"), "")

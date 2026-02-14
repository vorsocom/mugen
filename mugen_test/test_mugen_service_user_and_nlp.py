"""Unit tests for user and NLP service defaults."""

import pickle
import unittest
from unittest.mock import Mock

from mugen.core.service.nlp import DefaultNLPService
from mugen.core.service.user import DefaultUserService


class TestMugenServiceUserAndNlp(unittest.TestCase):
    """Tests key-value backed user methods and NLP default behavior."""

    def test_get_known_users_list_returns_empty_without_storage_key(self) -> None:
        keyval = Mock()
        keyval.has_key.return_value = False
        svc = DefaultUserService(
            keyval_storage_gateway=keyval,
            logging_gateway=Mock(),
        )

        self.assertEqual(svc.get_known_users_list(), {})
        keyval.get.assert_not_called()

    def test_get_known_users_list_unpickles_when_key_exists(self) -> None:
        payload = {"u1": {"displayname": "Alice", "dm_id": "!room"}}
        keyval = Mock()
        keyval.has_key.return_value = True
        keyval.get.return_value = pickle.dumps(payload)
        svc = DefaultUserService(
            keyval_storage_gateway=keyval,
            logging_gateway=Mock(),
        )

        self.assertEqual(svc.get_known_users_list(), payload)
        keyval.get.assert_called_once_with("known_users_list", False)

    def test_add_known_user_and_display_name_paths(self) -> None:
        keyval = Mock()
        keyval.has_key.return_value = True
        keyval.get.return_value = pickle.dumps({})
        svc = DefaultUserService(
            keyval_storage_gateway=keyval,
            logging_gateway=Mock(),
        )

        svc.add_known_user(user_id="@alice", displayname="Alice", room_id="!dm")
        known_users = pickle.loads(keyval.put.call_args.args[1])
        keyval.get.return_value = keyval.put.call_args.args[1]

        self.assertEqual(known_users["@alice"]["displayname"], "Alice")
        self.assertEqual(known_users["@alice"]["dm_id"], "!dm")
        self.assertEqual(svc.get_user_display_name("@alice"), "Alice")
        self.assertEqual(svc.get_user_display_name("@missing"), "")

    def test_save_known_users_list_serializes_payload(self) -> None:
        keyval = Mock()
        svc = DefaultUserService(
            keyval_storage_gateway=keyval,
            logging_gateway=Mock(),
        )
        payload = {"u2": {"displayname": "Bob", "dm_id": "!room2"}}

        svc.save_known_users_list(payload)

        keyval.put.assert_called_once()
        stored = keyval.put.call_args.args[1]
        self.assertEqual(pickle.loads(stored), payload)

    def test_default_nlp_service_returns_empty_keywords(self) -> None:
        svc = DefaultNLPService(logging_gateway=Mock())
        self.assertEqual(svc.get_keywords("hello world"), [])

"""Unit tests for mugen.core.gateway.storage.keyval.dbm.DBMKeyValStorageGateway."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mugen.core.gateway.storage.keyval.dbm import DBMKeyValStorageGateway


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        mugen=SimpleNamespace(
            storage=SimpleNamespace(
                keyval=SimpleNamespace(
                    dbm=SimpleNamespace(path="/tmp/test-keyval.db"),
                )
            )
        )
    )


class _FakeStorage:
    def __init__(self, initial=None, *, delete_error: str | None = None):
        self._data = dict(initial or {})
        self._delete_error = delete_error
        self.closed = False

    def __setitem__(self, key, value):
        norm_key = key.encode() if isinstance(key, str) else key
        norm_value = value.encode() if isinstance(value, str) else value
        self._data[norm_key] = norm_value

    def get(self, key):
        norm_key = key.encode() if isinstance(key, str) else key
        return self._data.get(norm_key)

    def __delitem__(self, key):
        if self._delete_error == "attribute":
            raise AttributeError("delete failed")
        if self._delete_error == "key":
            raise KeyError("delete failed")
        norm_key = key.encode() if isinstance(key, str) else key
        del self._data[norm_key]

    def keys(self):
        return list(self._data.keys())

    def close(self):
        self.closed = True


class TestMugenGatewayStorageKeyvalDbm(unittest.TestCase):
    """Covers happy-path and exception-path behavior for DBM key/value gateway."""

    def test_put_get_keys_remove_has_key_and_close(self) -> None:
        storage = _FakeStorage()
        logging_gateway = Mock()

        with patch(
            "mugen.core.gateway.storage.keyval.dbm._gdbm.open", return_value=storage
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        gateway.put("alpha", "one")
        self.assertEqual(gateway.get("alpha"), "one")
        self.assertEqual(gateway.get("alpha", decode=False), b"one")
        self.assertEqual(gateway.keys(), ["alpha"])
        self.assertTrue(gateway.has_key("alpha"))
        self.assertEqual(gateway.remove("alpha"), b"one")
        self.assertFalse(gateway.has_key("alpha"))

        gateway.close()
        self.assertTrue(storage.closed)

    def test_get_handles_attribute_error(self) -> None:
        storage = _FakeStorage(initial={b"alpha": 123})
        logging_gateway = Mock()

        with patch(
            "mugen.core.gateway.storage.keyval.dbm._gdbm.open", return_value=storage
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        with patch(
            "mugen.core.gateway.storage.keyval.dbm.traceback.print_exc"
        ) as print_exc:
            result = gateway.get("alpha")

        self.assertIsNone(result)
        logging_gateway.warning.assert_called_once_with("AttributeError:")
        print_exc.assert_called_once()

    def test_remove_handles_attribute_error(self) -> None:
        storage = _FakeStorage(initial={b"alpha": b"one"}, delete_error="attribute")
        logging_gateway = Mock()

        with patch(
            "mugen.core.gateway.storage.keyval.dbm._gdbm.open", return_value=storage
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        with patch(
            "mugen.core.gateway.storage.keyval.dbm.traceback.print_exc"
        ) as print_exc:
            result = gateway.remove("alpha")

        self.assertIsNone(result)
        logging_gateway.warning.assert_called_once_with("AttributeError:")
        print_exc.assert_called_once()

    def test_remove_handles_key_error(self) -> None:
        storage = _FakeStorage(initial={b"alpha": b"one"}, delete_error="key")
        logging_gateway = Mock()

        with patch(
            "mugen.core.gateway.storage.keyval.dbm._gdbm.open", return_value=storage
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        with patch(
            "mugen.core.gateway.storage.keyval.dbm.traceback.print_exc"
        ) as print_exc:
            result = gateway.remove("alpha")

        self.assertIsNone(result)
        logging_gateway.warning.assert_called_once_with("KeyError")
        print_exc.assert_called_once()

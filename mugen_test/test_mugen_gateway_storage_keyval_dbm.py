"""Unit tests for mugen.core.gateway.storage.keyval.dbm.DBMKeyValStorageGateway."""

import asyncio
import _gdbm
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mugen.core.gateway.storage.keyval.dbm import DBMKeyValStorageGateway


def _make_config(
    *,
    path: str = "/tmp/test-keyval.db",
    basedir: str | None = None,
    environment: str = "development",
    allow_non_dev: bool = False,
) -> SimpleNamespace:
    config = SimpleNamespace(
        mugen=SimpleNamespace(
            environment=environment,
            storage=SimpleNamespace(
                keyval=SimpleNamespace(
                    dbm=SimpleNamespace(
                        path=path,
                        allow_non_dev=allow_non_dev,
                    ),
                )
            )
        )
    )
    if basedir is not None:
        config.basedir = basedir
    return config


class _FakeStorage:
    def __init__(
        self,
        initial=None,
        *,
        contains_error: bool = False,
        delete_error: str | None = None,
        keys_error: bool = False,
        read_error: bool = False,
        close_error: bool = False,
    ):
        self._data = dict(initial or {})
        self._contains_error = contains_error
        self._delete_error = delete_error
        self._keys_error = keys_error
        self._read_error = read_error
        self._close_error = close_error
        self.closed = False

    def __setitem__(self, key, value):
        norm_key = key.encode() if isinstance(key, str) else key
        norm_value = value.encode() if isinstance(value, str) else value
        self._data[norm_key] = norm_value

    def get(self, key):
        if self._read_error:
            raise _gdbm.error("read failed")
        norm_key = key.encode() if isinstance(key, str) else key
        return self._data.get(norm_key)

    def __delitem__(self, key):
        if self._delete_error == "key":
            raise KeyError("delete failed")
        if self._delete_error == "gdbm":
            raise _gdbm.error("delete failed")
        norm_key = key.encode() if isinstance(key, str) else key
        del self._data[norm_key]

    def __contains__(self, key):
        if self._contains_error:
            raise TypeError("contains failed")
        norm_key = key.encode() if isinstance(key, str) else key
        return norm_key in self._data

    def keys(self):
        if self._keys_error:
            raise _gdbm.error("keys failed")
        return list(self._data.keys())

    def close(self):
        if self._close_error:
            raise _gdbm.error("close failed")
        self.closed = True


class TestMugenGatewayStorageKeyvalDbm(unittest.TestCase):
    """Covers happy-path and hardening behavior for DBM key/value gateway."""

    def test_init_resolves_relative_path_and_hardens_permissions(self) -> None:
        storage = _FakeStorage()
        config = _make_config(path="data/storage.db", basedir="/srv/mugen")
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs") as makedirs,
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod") as chmod,
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ) as open_db,
        ):
            DBMKeyValStorageGateway(config, logging_gateway)

        open_db.assert_called_once_with("/srv/mugen/data/storage.db", "c", 0o600)
        makedirs.assert_called_once_with("/srv/mugen/data", exist_ok=True)
        chmod.assert_called_once_with("/srv/mugen/data/storage.db", 0o600)

    def test_init_blocks_non_dev_when_override_not_set(self) -> None:
        config = _make_config(environment="production", allow_non_dev=False)
        logging_gateway = Mock()

        with self.assertRaises(RuntimeError) as ctx:
            DBMKeyValStorageGateway(config, logging_gateway)

        self.assertIn("disabled for non-development use", str(ctx.exception))
        logging_gateway.error.assert_called_once()

    def test_init_allows_non_dev_when_override_enabled(self) -> None:
        storage = _FakeStorage()
        config = _make_config(environment="production", allow_non_dev=True)
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ) as open_db,
        ):
            DBMKeyValStorageGateway(config, logging_gateway)

        open_db.assert_called_once()

    def test_init_uses_absolute_path(self) -> None:
        storage = _FakeStorage()
        config = _make_config(path="/tmp/storage.db", basedir="/ignored")
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs") as makedirs,
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod") as chmod,
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ) as open_db,
        ):
            DBMKeyValStorageGateway(config, logging_gateway)

        open_db.assert_called_once_with("/tmp/storage.db", "c", 0o600)
        makedirs.assert_called_once_with("/tmp", exist_ok=True)
        chmod.assert_called_once_with("/tmp/storage.db", 0o600)

    def test_init_raises_runtime_error_when_dbm_open_fails(self) -> None:
        config = _make_config(path="/tmp/storage.db")
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                side_effect=_gdbm.error("Resource temporarily unavailable"),
            ),
            self.assertRaises(RuntimeError) as ctx,
        ):
            DBMKeyValStorageGateway(config, logging_gateway)

        self.assertIn("single-process", str(ctx.exception))
        self.assertEqual(logging_gateway.error.call_count, 2)

    def test_init_resolves_relative_path_without_basedir(self) -> None:
        storage = _FakeStorage()
        config = _make_config(path="storage.db")
        logging_gateway = Mock()
        expected_path = os.path.abspath("storage.db")
        expected_dir = os.path.dirname(expected_path)

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs") as makedirs,
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod") as chmod,
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ) as open_db,
        ):
            DBMKeyValStorageGateway(config, logging_gateway)

        open_db.assert_called_once_with(expected_path, "c", 0o600)
        makedirs.assert_called_once_with(expected_dir, exist_ok=True)
        chmod.assert_called_once_with(expected_path, 0o600)

    def test_init_skips_makedirs_for_path_without_directory_component(self) -> None:
        storage = _FakeStorage()
        logging_gateway = Mock()

        with (
            patch(
                "mugen.core.gateway.storage.keyval.dbm."
                "DBMKeyValStorageGateway._resolve_storage_path",
                return_value="storage.db",
            ),
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs") as makedirs,
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ) as open_db,
        ):
            DBMKeyValStorageGateway(_make_config(path="storage.db"), logging_gateway)

        open_db.assert_called_once_with("storage.db", "c", 0o600)
        makedirs.assert_not_called()

    def test_init_warns_when_permission_hardening_fails(self) -> None:
        storage = _FakeStorage()
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm.os.chmod",
                side_effect=OSError("chmod failed"),
            ),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ),
        ):
            DBMKeyValStorageGateway(_make_config(), logging_gateway)

        logging_gateway.warning.assert_called_once()
        self.assertIn(
            "Could not set DBM file permissions to 0o600",
            logging_gateway.warning.call_args.args[0],
        )

    def test_put_get_keys_remove_has_key_and_close(self) -> None:
        storage = _FakeStorage()
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ),
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

    def test_aclose_calls_close(self) -> None:
        storage = _FakeStorage()
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ),
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        close_spy = Mock(wraps=gateway.close)
        gateway.close = close_spy

        asyncio.run(gateway.aclose())

        close_spy.assert_called_once()

    def test_get_returns_none_for_invalid_utf8(self) -> None:
        storage = _FakeStorage(initial={b"alpha": b"\xff"})
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ),
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        self.assertIsNone(gateway.get("alpha"))
        logging_gateway.warning.assert_called_once_with(
            "DBM value for key 'alpha' is not valid UTF-8."
        )

    def test_get_handles_storage_read_error(self) -> None:
        storage = _FakeStorage(read_error=True)
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ),
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        self.assertIsNone(gateway.get("alpha"))
        logging_gateway.warning.assert_called_once_with(
            "Failed to read DBM key 'alpha' (read failed)."
        )

    def test_get_returns_plain_string_values(self) -> None:
        storage = _FakeStorage(initial={b"alpha": "one"})
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ),
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        self.assertEqual(gateway.get("alpha"), "one")

    def test_get_warns_for_unsupported_value_type(self) -> None:
        storage = _FakeStorage(initial={b"alpha": 123})
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ),
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        self.assertIsNone(gateway.get("alpha"))
        logging_gateway.warning.assert_called_once_with(
            "DBM value for key 'alpha' has unsupported type int."
        )

    def test_keys_skips_non_utf8_entries(self) -> None:
        storage = _FakeStorage(initial={b"alpha": b"one", b"\xff": b"bad"})
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ),
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        self.assertEqual(gateway.keys(), ["alpha"])
        logging_gateway.warning.assert_called_once_with(
            "Skipping non-UTF-8 key in DBM store."
        )

    def test_keys_handles_storage_error(self) -> None:
        storage = _FakeStorage(keys_error=True)
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ),
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        self.assertEqual(gateway.keys(), [])
        logging_gateway.warning.assert_called_once_with(
            "Failed to list DBM keys (keys failed)."
        )

    def test_keys_support_predecoded_string_keys(self) -> None:
        storage = _FakeStorage(initial={"alpha": b"one"})
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ),
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        self.assertEqual(gateway.keys(), ["alpha"])

    def test_keys_warns_for_unsupported_key_type(self) -> None:
        storage = _FakeStorage(initial={1: b"one"})
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ),
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        self.assertEqual(gateway.keys(), [])
        logging_gateway.warning.assert_called_once_with(
            "Skipping unsupported DBM key type int."
        )

    def test_remove_missing_key_returns_none_and_warns(self) -> None:
        storage = _FakeStorage()
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ),
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        self.assertIsNone(gateway.remove("missing"))
        logging_gateway.warning.assert_called_once_with(
            "DBM key not found for remove: 'missing'."
        )

    def test_remove_handles_storage_read_error(self) -> None:
        storage = _FakeStorage(read_error=True)
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ),
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        self.assertIsNone(gateway.remove("alpha"))
        logging_gateway.warning.assert_called_once_with(
            "Failed to read DBM key before remove 'alpha' (read failed)."
        )

    def test_remove_handles_delete_key_error(self) -> None:
        storage = _FakeStorage(initial={b"alpha": b"one"}, delete_error="key")
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ),
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        self.assertIsNone(gateway.remove("alpha"))
        logging_gateway.warning.assert_called_once_with(
            "DBM key missing during remove: 'alpha'."
        )

    def test_remove_handles_delete_gdbm_error(self) -> None:
        storage = _FakeStorage(initial={b"alpha": b"one"}, delete_error="gdbm")
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ),
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        self.assertIsNone(gateway.remove("alpha"))
        logging_gateway.warning.assert_called_once_with(
            "Failed to remove DBM key 'alpha' (delete failed)."
        )

    def test_has_key_handles_membership_error(self) -> None:
        storage = _FakeStorage(contains_error=True)
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ),
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        self.assertFalse(gateway.has_key("alpha"))
        logging_gateway.warning.assert_called_once_with(
            "Failed membership check for DBM key 'alpha' (contains failed)."
        )

    def test_close_handles_storage_error(self) -> None:
        storage = _FakeStorage(close_error=True)
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.storage.keyval.dbm.os.makedirs"),
            patch("mugen.core.gateway.storage.keyval.dbm.os.chmod"),
            patch(
                "mugen.core.gateway.storage.keyval.dbm._gdbm.open",
                return_value=storage,
            ),
        ):
            gateway = DBMKeyValStorageGateway(_make_config(), logging_gateway)

        gateway.close()
        logging_gateway.warning.assert_called_once_with(
            "Failed to close DBM key-value store (close failed)."
        )

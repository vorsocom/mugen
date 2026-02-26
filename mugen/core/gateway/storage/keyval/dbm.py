"""Provides a dbm.gnu based key-value storage gateway."""

__all__ = ["DBMKeyValStorageGateway"]

import asyncio
import os
from types import SimpleNamespace
import threading
import _gdbm

from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway


class DBMKeyValStorageGateway(IKeyValStorageGateway):
    """A dbm.gnu based key-value storage gateway.

    Relative paths are resolved against ``config.basedir`` when available.
    """

    _storage: object
    _storage_path: str

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._config = config
        self._logging_gateway = logging_gateway
        self._lock = threading.RLock()
        self._validate_environment_policy()
        configured_path = self._config.mugen.storage.keyval.dbm.path
        self._storage_path = self._resolve_storage_path(configured_path)

        try:
            self._ensure_storage_directory()
            self._storage = _gdbm.open(self._storage_path, "c", 0o600)
        except (_gdbm.error, OSError) as exc:
            self._logging_gateway.error(
                "Failed to open DBM key-value store. DBM requires single-process "
                "access and a writable storage path."
            )
            self._logging_gateway.error(
                f"DBM path={self._storage_path!r} open_error={exc}"
            )
            raise RuntimeError(
                "Unable to initialize DBM key-value store; ensure single-process "
                "access to the storage file."
            ) from exc

        self._harden_storage_permissions()

    def _validate_environment_policy(self) -> None:
        environment = getattr(
            getattr(self._config, "mugen", SimpleNamespace()),
            "environment",
            "development",
        )
        allow_non_dev = getattr(
            getattr(
                getattr(
                    getattr(
                        getattr(self._config, "mugen", SimpleNamespace()),
                        "storage",
                        SimpleNamespace(),
                    ),
                    "keyval",
                    SimpleNamespace(),
                ),
                "dbm",
                SimpleNamespace(),
            ),
            "allow_non_dev",
            False,
        )

        if bool(allow_non_dev):
            return

        if str(environment).strip().lower() in {"development", "dev", "testing"}:
            return

        self._logging_gateway.error(
            "DBM key-value backend is blocked outside development/test environments. "
            "Use relational keyval or set mugen.storage.keyval.dbm.allow_non_dev=true "
            "to override explicitly."
        )
        raise RuntimeError("DBM key-value backend is disabled for non-development use.")

    def _resolve_storage_path(self, configured_path: str) -> str:
        if os.path.isabs(configured_path):
            return configured_path

        basedir = getattr(self._config, "basedir", None)
        if isinstance(basedir, str) and basedir != "":
            return os.path.join(basedir, configured_path)

        return os.path.abspath(configured_path)

    def _ensure_storage_directory(self) -> None:
        storage_directory = os.path.dirname(self._storage_path)
        if storage_directory != "":
            os.makedirs(storage_directory, exist_ok=True)

    def _harden_storage_permissions(self) -> None:
        try:
            os.chmod(self._storage_path, 0o600)
        except OSError as exc:
            self._logging_gateway.warning(
                f"Could not set DBM file permissions to 0o600 ({exc})."
            )

    def put(self, key: str, value: str | bytes) -> None:
        with self._lock:
            self._storage[key] = value

    def get(self, key: str, decode: bool = True) -> str | bytes | None:
        try:
            with self._lock:
                value = self._storage.get(key)
        except (_gdbm.error, OSError) as exc:
            self._logging_gateway.warning(f"Failed to read DBM key {key!r} ({exc}).")
            return None

        if value is None or decode is False:
            return value

        if isinstance(value, str):
            return value

        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                self._logging_gateway.warning(
                    f"DBM value for key {key!r} is not valid UTF-8."
                )
                return None

        self._logging_gateway.warning(
            f"DBM value for key {key!r} has unsupported type {type(value).__name__}."
        )
        return None

    def keys(self) -> list[str]:
        try:
            with self._lock:
                raw_keys = self._storage.keys()
        except (_gdbm.error, OSError) as exc:
            self._logging_gateway.warning(f"Failed to list DBM keys ({exc}).")
            return []

        decoded_keys: list[str] = []
        for raw_key in raw_keys:
            if isinstance(raw_key, str):
                decoded_keys.append(raw_key)
                continue

            if isinstance(raw_key, bytes):
                try:
                    decoded_keys.append(raw_key.decode("utf-8"))
                except UnicodeDecodeError:
                    self._logging_gateway.warning(
                        "Skipping non-UTF-8 key in DBM store."
                    )
                continue

            self._logging_gateway.warning(
                f"Skipping unsupported DBM key type {type(raw_key).__name__}."
            )

        return decoded_keys

    def remove(self, key: str) -> str | bytes | None:
        try:
            with self._lock:
                value = self._storage.get(key)
        except (_gdbm.error, OSError) as exc:
            self._logging_gateway.warning(
                f"Failed to read DBM key before remove {key!r} ({exc})."
            )
            return None

        if value is None:
            self._logging_gateway.warning(f"DBM key not found for remove: {key!r}.")
            return None

        try:
            with self._lock:
                del self._storage[key]
                return value
        except KeyError:
            self._logging_gateway.warning(f"DBM key missing during remove: {key!r}.")
        except (_gdbm.error, OSError) as exc:
            self._logging_gateway.warning(f"Failed to remove DBM key {key!r} ({exc}).")
        return None

    def has_key(self, key: str) -> bool:
        try:
            with self._lock:
                return key in self._storage
        except (_gdbm.error, OSError, TypeError) as exc:
            self._logging_gateway.warning(
                f"Failed membership check for DBM key {key!r} ({exc})."
            )
            return False

    def close(self) -> None:
        try:
            with self._lock:
                self._storage.close()
        except (_gdbm.error, OSError) as exc:
            self._logging_gateway.warning(
                f"Failed to close DBM key-value store ({exc})."
            )

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)

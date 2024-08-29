"""Provides a dbm.gnu based key-value storage gateway."""

__all__ = ["DBMKeyValStorageGateway"]

import dbm.gnu as dbm
import traceback
from types import SimpleNamespace
import _gdbm

from app.core.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.core.contract.logging_gateway import ILoggingGateway


class DBMKeyValStorageGateway(IKeyValStorageGateway):
    """A dbm.gnu based key-value storage gateway."""

    _storage: _gdbm

    def __init__(
        self,
        config: dict,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._config = SimpleNamespace(**config)
        self._logging_gateway = logging_gateway
        self._storage = dbm.open(self._config.keyval_storage_path, "c")

    def put(self, key: str, value: str) -> None:
        self._storage[key] = value

    def get(self, key: str, decode: bool = True) -> str | None:
        try:
            value = self._storage.get(key)
            return value.decode() if decode is True and value is not None else value
        except AttributeError:
            self._logging_gateway.warning(
                "dbm_keyval_storage_gateway-get: AttributeError:"
            )
            traceback.print_exc()
        return None

    def keys(self) -> list[str]:
        return [x.decode() for x in self._storage.keys()]

    def remove(self, key: str) -> str | None:
        try:
            value = self._storage.get(key)
            del self._storage[key]
            return value
        except AttributeError:
            self._logging_gateway.warning(
                "dbm_keyval_storage_gateway-remove: AttributeError:"
            )
            traceback.print_exc()
        except KeyError:
            self._logging_gateway.warning("dbm_keyval_storage_gateway-remove: KeyError")
            traceback.print_exc()
        return None

    def has_key(self, key: str) -> bool:
        return key.encode() in self._storage.keys()

    def close(self) -> None:
        self._storage.close()

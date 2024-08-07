"""Provides a dbm.gnu based key-value storage gateway."""

__all__ = ["DBMKeyValStorageGateway"]

import dbm.gnu as dbm
import traceback
from typing import Optional
import _gdbm

from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.logging_gateway import ILoggingGateway


class DBMKeyValStorageGateway(IKeyValStorageGateway):
    """A dbm.gnu based key-value storage gateway."""

    _storage: _gdbm

    def __init__(
        self,
        storage_path: str,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._storage = dbm.open(storage_path, "c")
        self._logging_gateway = logging_gateway

    def put(self, key: str, value: str) -> None:
        self._storage[key] = value

    def get(self, key: str, decode: bool = True) -> Optional[str]:
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

    def remove(self, key: str) -> Optional[str]:
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

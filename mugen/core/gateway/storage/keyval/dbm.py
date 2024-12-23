"""Provides a dbm.gnu based key-value storage gateway."""

__all__ = ["DBMKeyValStorageGateway"]

from types import SimpleNamespace
import traceback
import _gdbm


from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.gateway.logging import ILoggingGateway


class DBMKeyValStorageGateway(IKeyValStorageGateway):
    """A dbm.gnu based key-value storage gateway."""

    _storage: _gdbm

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._config = config
        self._logging_gateway = logging_gateway
        self._storage = _gdbm.open(self._config.mugen.storage.keyval.dbm.path, "c")

    def put(self, key: str, value: str) -> None:
        self._storage[key] = value

    def get(self, key: str, decode: bool = True) -> str | None:
        try:
            value = self._storage.get(key)
            return value.decode() if decode is True and value is not None else value
        except AttributeError:
            self._logging_gateway.warning("AttributeError:")
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
            self._logging_gateway.warning("AttributeError:")
            traceback.print_exc()
        except KeyError:
            self._logging_gateway.warning("KeyError")
            traceback.print_exc()
        return None

    def has_key(self, key: str) -> bool:
        return key.encode() in self._storage.keys()

    def close(self) -> None:
        self._storage.close()

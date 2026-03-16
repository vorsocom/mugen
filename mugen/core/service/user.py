"""Provides an implementation of IUserService."""

__all__ = ["DefaultUserService"]

from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.gateway.storage.keyval_model import KeyValConflictError
from mugen.core.contract.service.user import IUserService


class DefaultUserService(IUserService):
    """The default implementation of IUserService."""

    _known_users_list_key: str = "known_users_list"
    _default_cas_retries: int = 5

    def __init__(
        self,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway

    async def add_known_user(
        self,
        user_id: str,
        displayname: str,
        room_id: str,
    ) -> None:
        last_conflict: KeyValConflictError | None = None
        for _ in range(self._default_cas_retries):
            entry = await self._keyval_storage_gateway.get_entry(self._known_users_list_key)
            expected_row_version = 0
            known_users: dict = {}

            if entry is not None:
                expected_row_version = int(entry.row_version)
                payload = entry.as_json()
                if isinstance(payload, dict):
                    known_users = dict(payload)
                else:
                    self._logging_gateway.warning(
                        "Invalid known users payload; resetting."
                    )

            known_users[user_id] = {
                "displayname": displayname,
                "dm_id": room_id,
            }

            try:
                await self._keyval_storage_gateway.put_json(
                    self._known_users_list_key,
                    known_users,
                    expected_row_version=expected_row_version,
                )
                return
            except KeyValConflictError as exc:
                last_conflict = exc
                continue

        if last_conflict is not None:
            raise last_conflict
        raise RuntimeError("Known users update retries exhausted without conflict details.")

    async def get_known_users_list(self) -> dict:
        payload = await self._keyval_storage_gateway.get_json(self._known_users_list_key)
        if isinstance(payload, dict):
            return payload

        if payload is not None:
            self._logging_gateway.warning("Invalid known users payload; resetting.")
        return {}

    async def get_user_display_name(self, user_id: str) -> str:
        known_users = await self.get_known_users_list()
        if user_id in known_users.keys():
            displayname = known_users[user_id].get("displayname")
            if isinstance(displayname, str):
                return displayname
        return ""

    async def save_known_users_list(self, known_users: dict) -> None:
        await self._keyval_storage_gateway.put_json(
            self._known_users_list_key,
            known_users,
        )

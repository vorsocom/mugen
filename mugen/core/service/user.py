"""Provides an implementation of IUserService."""

__all__ = ["DefaultUserService"]

import pickle

from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.user import IUserService


class DefaultUserService(IUserService):
    """The default implementation of IUserService."""

    _known_users_list_key: str = "known_users_list"

    def __init__(
        self,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway

    def add_known_user(self, user_id: str, displayname: str, room_id: str) -> None:
        known_users = self.get_known_users_list()
        known_users[user_id] = {
            "displayname": displayname,
            "dm_id": room_id,
        }
        self.save_known_users_list(known_users)

    def get_known_users_list(self) -> dict:
        if self._keyval_storage_gateway.has_key(self._known_users_list_key):
            return pickle.loads(
                self._keyval_storage_gateway.get(self._known_users_list_key, False)
            )

        return {}

    def get_user_display_name(self, user_id: str):
        known_users = self.get_known_users_list()
        if user_id in known_users.keys():
            return known_users[user_id]["displayname"]
        return ""

    def save_known_users_list(self, known_users: dict) -> None:
        self._keyval_storage_gateway.put(
            self._known_users_list_key, pickle.dumps(known_users)
        )

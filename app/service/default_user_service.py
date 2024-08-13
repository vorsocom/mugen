"""Provides an implementation of IUserService."""

__all__ = ["DefaultUserService"]

import pickle

from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.logging_gateway import ILoggingGateway
from app.contract.user_service import IUserService

KNOWN_USERS_LIST_KEY: str = "known_users_list"


class DefaultUserService(IUserService):
    """The default implementation of IUserService."""

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
        if self._keyval_storage_gateway.has_key(KNOWN_USERS_LIST_KEY):
            return pickle.loads(
                self._keyval_storage_gateway.get(KNOWN_USERS_LIST_KEY, False)
            )

        return {}

    def save_known_users_list(self, known_users: dict) -> None:
        self._keyval_storage_gateway.put(
            KNOWN_USERS_LIST_KEY, pickle.dumps(known_users)
        )

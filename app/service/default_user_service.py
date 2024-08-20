"""Provides an implementation of IUserService."""

__all__ = ["DefaultUserService"]

import pickle

from nio import AsyncClient

from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.logging_gateway import ILoggingGateway
from app.contract.user_service import IUserService

KNOWN_DEVICES_LIST_KEY: str = "known_devices_list"

KNOWN_USERS_LIST_KEY: str = "known_users_list"


class DefaultUserService(IUserService):
    """The default implementation of IUserService."""

    def __init__(
        self,
        client: AsyncClient,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._client = client
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway

    def add_known_user(self, user_id: str, displayname: str, room_id: str) -> None:
        known_users = self.get_known_users_list()
        known_users[user_id] = {
            "displayname": displayname,
            "dm_id": room_id,
        }
        self.save_known_users_list(known_users)

    def cleanup_known_user_devices_list(self) -> None:
        self._logging_gateway.debug("Cleaning up known user devices.")
        if self._keyval_storage_gateway.has_key(KNOWN_DEVICES_LIST_KEY):
            known_devices = pickle.loads(
                self._keyval_storage_gateway.get(KNOWN_DEVICES_LIST_KEY, False)
            )
            for user_id in known_devices.keys():
                active_devices = [
                    x.device_id
                    for x in self._client.device_store.active_user_devices(user_id)
                ]
                self._logging_gateway.debug(f"Active devices: {active_devices}")
                known_devices[user_id] = active_devices

            # Persist changes.
            self._keyval_storage_gateway.put(
                KNOWN_DEVICES_LIST_KEY, pickle.dumps(known_devices)
            )

    def get_known_users_list(self) -> dict:
        if self._keyval_storage_gateway.has_key(KNOWN_USERS_LIST_KEY):
            return pickle.loads(
                self._keyval_storage_gateway.get(KNOWN_USERS_LIST_KEY, False)
            )

        return {}

    def get_user_display_name(self, user_id: str):
        known_users = self.get_known_users_list()
        if user_id in known_users.keys():
            return known_users[user_id]["displayname"]
        return ""

    def save_known_users_list(self, known_users: dict) -> None:
        self._keyval_storage_gateway.put(
            KNOWN_USERS_LIST_KEY, pickle.dumps(known_users)
        )

    def trust_known_user_devices(self) -> None:
        self._logging_gateway.debug("Trusting all known user devices.")
        if self._keyval_storage_gateway.has_key(KNOWN_DEVICES_LIST_KEY):
            known_devices = pickle.loads(
                self._keyval_storage_gateway.get(KNOWN_DEVICES_LIST_KEY, False)
            )
            for user_id in known_devices.keys():
                for device_id, olm_device in self._client.device_store[user_id].items():
                    if device_id in known_devices[user_id]:
                        # Verify the device.
                        self._logging_gateway.debug(f"Trusting {device_id}.")
                        self._client.verify_device(olm_device)

    def verify_user_devices(self, user_id: str) -> None:
        self._logging_gateway.debug("Verifying all user devices.")
        # This has to be revised when we figure out a trust mechanism.
        # A solution might be to require users to visit sys admin to perform SAS
        # verification whenever using a new device.
        for device_id, olm_device in self._client.device_store[user_id].items():
            known_devices = {}
            # Load the known devices list if it already exists.
            if self._keyval_storage_gateway.has_key(KNOWN_DEVICES_LIST_KEY):
                known_devices = pickle.loads(
                    self._keyval_storage_gateway.get(KNOWN_DEVICES_LIST_KEY, False)
                )

            # If the list (new or loaded) does not contain an entry for the user.
            if user_id not in known_devices.keys():
                # Add an entry for the user.
                known_devices[user_id] = []

            # If the device is not already in the known devices list for the user.
            if device_id not in known_devices[user_id]:
                # Add the device id to the list of known devices for the user.
                known_devices[user_id].append(device_id)

                # Verify the device.
                self._logging_gateway.debug(f"Verifying {device_id}.")
                self._client.verify_device(olm_device)

                # Persist changes to the known devices list.
                self._keyval_storage_gateway.put(
                    KNOWN_DEVICES_LIST_KEY, pickle.dumps(known_devices)
                )

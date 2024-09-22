"""Provides an implementation of the nio.AsyncClient."""

__all__ = ["DefaultMatrixClient"]

import asyncio
import pickle
import sys
import traceback
from typing import Coroutine

from dependency_injector import providers
from nio import (
    AsyncClient,
    InviteAliasEvent,
    InviteMemberEvent,
    InviteNameEvent,
    KeyVerificationEvent,
    LocalProtocolError,
    LoginResponse,
    MatrixInvitedRoom,
    MatrixRoom,
    MegolmEvent,
    ProfileGetResponse,
    RoomCreateEvent,
    RoomKeyEvent,
    RoomKeyRequest,
    RoomMessage,
    RoomEncryptedAudio,
    RoomEncryptedFile,
    RoomEncryptedImage,
    RoomEncryptedVideo,
    RoomMessageText,
    RoomMemberEvent,
    SendRetryError,
    SyncResponse,
    TagEvent,
)

from nio.exceptions import OlmUnverifiedDeviceError

from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.user import IUserService


class DefaultMatrixClient(AsyncClient):  # pylint: disable=too-many-instance-attributes
    """A custom implementation of nio.AsyncClient."""

    _flags_key: str = "m.agent_flags"

    _ipc_callback: Coroutine

    _known_devices_list_key: str = "known_devices_list"

    _sync_key: str = "matrix_client_sync_next_batch"

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        # pylint: disable=c-extension-no-member
        config: providers.Configuration = None,
        ipc_queue: asyncio.Queue = None,
        ipc_service: IIPCService = None,
        keyval_storage_gateway: IKeyValStorageGateway = None,
        logging_gateway: ILoggingGateway = None,
        messaging_service: IMessagingService = None,
        user_service: IUserService = None,
    ):
        self._config = config
        super().__init__(
            homeserver=self._config.matrix.homeserver(),
            user=self._config.matrix.client_user(),
            store_path=self._config.matrix.olm_store_path(),
        )
        self._ipc_queue = ipc_queue
        self._ipc_service = ipc_service
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._messaging_service = messaging_service
        self._user_service = user_service

        ## Callbacks
        # Invite Room Events.
        self.add_event_callback(self._cb_invite_alias_event, InviteAliasEvent)
        self.add_event_callback(self._cb_invite_member_event, InviteMemberEvent)
        self.add_event_callback(self._cb_invite_name_event, InviteNameEvent)

        # Room Events.
        self.add_event_callback(self._cb_megolm_event, MegolmEvent)
        self.add_event_callback(self._cb_room_create_event, RoomCreateEvent)
        self.add_event_callback(self._cb_room_member_event, RoomMemberEvent)
        self.add_event_callback(self._cb_room_message, RoomMessage)
        self.add_event_callback(self._cb_room_message_text, RoomMessageText)

        # To-device Events.
        self.add_to_device_callback(
            self._cb_key_verification_event, KeyVerificationEvent
        )
        self.add_to_device_callback(self._cb_room_key_event, RoomKeyEvent)
        self.add_to_device_callback(self._cb_room_key_request, RoomKeyRequest)

        # Responses.
        self.add_response_callback(self._cb_sync_response, SyncResponse)

    async def __aenter__(self) -> None:
        """Initialisation."""
        self._logging_gateway.debug("DefaultMatrixClient.__aenter__")
        if self._keyval_storage_gateway.get("client_access_token") is None:
            # Load password and device name from storage.
            pw = self._config.matrix.client.password()
            dn = self._config.matrix.client.device()

            # Attempt  password login.
            resp = await self.login(pw, dn)

            # check login successful
            if isinstance(resp, LoginResponse):
                self._logging_gateway.debug("Password login successful.")
                self._logging_gateway.debug("Saving credentials.")

                # Save credentials.
                self._keyval_storage_gateway.put(
                    "client_access_token", resp.access_token
                )
                self._keyval_storage_gateway.put("client_device_id", resp.device_id)
                self._keyval_storage_gateway.put("client_user_id", resp.user_id)
            else:
                self._logging_gateway.debug("Password login failed.")
                sys.exit(1)
            sys.exit(0)

        # Otherwise the config file exists, so we'll use the stored credentials.
        self._logging_gateway.debug("Login using saved credentials.")
        # open the file in read-only mode.
        self.access_token = self._keyval_storage_gateway.get("client_access_token")
        self.device_id = self._keyval_storage_gateway.get("client_device_id")
        self.user_id = self._keyval_storage_gateway.get("client_user_id")
        self.load_store()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Finalisation."""
        self._logging_gateway.debug("DefaultMatrixClient.__aexit__")
        try:
            await self.client_session.close()
        except AttributeError:
            ...

    @property
    def sync_token(self) -> str:
        """Get the key to access the sync key from persistent storage."""
        return self._keyval_storage_gateway.get(self._sync_key)

    def cleanup_known_user_devices_list(self) -> None:
        """Clean up known user devices list."""
        self._logging_gateway.debug("Cleaning up known user devices.")
        if self._keyval_storage_gateway.has_key(self._known_devices_list_key):
            known_devices = pickle.loads(
                self._keyval_storage_gateway.get(self._known_devices_list_key, False)
            )
            for user_id in known_devices.keys():
                active_devices = [
                    x.device_id for x in self.device_store.active_user_devices(user_id)
                ]
                self._logging_gateway.debug(f"Active devices: {active_devices}")
                known_devices[user_id] = active_devices

            # Persist changes.
            self._keyval_storage_gateway.put(
                self._known_devices_list_key, pickle.dumps(known_devices)
            )

    def trust_known_user_devices(self) -> None:
        """Trust all known user devices."""
        self._logging_gateway.debug("Trusting all known user devices.")
        if self._keyval_storage_gateway.has_key(self._known_devices_list_key):
            known_devices = pickle.loads(
                self._keyval_storage_gateway.get(self._known_devices_list_key, False)
            )
            for user_id in known_devices.keys():
                self._logging_gateway.debug(f"User: {user_id}")
                for device_id, olm_device in self.device_store[user_id].items():
                    if device_id in known_devices[user_id]:
                        # Verify the device.
                        self._logging_gateway.debug(f"Trusting {device_id}.")
                        self.verify_device(olm_device)

    def verify_user_devices(self, user_id: str) -> None:
        """Verify all of a user's devices."""
        self._logging_gateway.debug(f"Verifying all user devices ({user_id}).")
        # This has to be revised when we figure out a trust mechanism.
        # A solution might be to require users to visit sys admin to perform SAS
        # verification whenever using a new device.
        for device_id, olm_device in self.device_store[user_id].items():
            self._logging_gateway.debug(f"Found {device_id}.")
            known_devices = {}
            # Load the known devices list if it already exists.
            if self._keyval_storage_gateway.has_key(self._known_devices_list_key):
                known_devices = pickle.loads(
                    self._keyval_storage_gateway.get(
                        self._known_devices_list_key, False
                    )
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
                self.verify_device(olm_device)

                # Persist changes to the known devices list.
                self._keyval_storage_gateway.put(
                    self._known_devices_list_key, pickle.dumps(known_devices)
                )

    ## Callbacks.
    # Events
    async def _cb_megolm_event(self, _room: MatrixRoom, _event: MegolmEvent) -> None:
        """Handle MegolmEvents."""
        self._logging_gateway.debug("MegolmEvent")

    async def _cb_invite_alias_event(self, _event: InviteAliasEvent) -> None:
        """Handle InviteAliasEvents."""

    async def _cb_invite_member_event(
        self, room: MatrixInvitedRoom, event: InviteMemberEvent
    ) -> None:
        """Handle InviteMemberEvents."""
        # Filter out events that do not have membership set to invite.
        membership = event.content.get("membership")
        if membership is not None and membership != "invite":
            return

        # Only process invites from allowed domains.
        # Federated servers need to be in the allowed domains list for their users
        # to initiate conversations with the assistant.
        allowed_domains: list = self._config.matrix.domains.allowed()
        denied_domains: list = self._config.matrix.domains.denied()
        sender_domain: str = event.sender.split(":")[1]
        if sender_domain not in allowed_domains or sender_domain in denied_domains:
            await self.room_leave(room.room_id)
            self._logging_gateway.warning(
                "InviteMemberEvent: Rejected invitation. Reason: Domain"
                f" not allowed. ({event.sender})"
            )
            return

        # If the assistant is in limited-beta mode, only process invites from the
        # list of selected beta users.
        if self._config.mugen.beta():
            beta_users: list = self._config.matrix.beta.users()
            if event.sender not in beta_users:
                await self.room_leave(room.room_id)
                self._logging_gateway.warning(
                    "InviteMemberEvent: Rejected invitation. Reason:"
                    f" Non-beta user. ({event.sender})"
                )
                return

        # Only accept invites to Direct Messages for now.
        is_direct = event.content.get("is_direct")
        if is_direct is None:
            await self.room_leave(room.room_id)
            self._logging_gateway.warning(
                "InviteMemberEvent: Rejected invitation. Reason: Not direct"
                f" message. ({event.sender})"
            )
            return

        # Verify user devices.
        self.verify_user_devices(event.sender)

        # Join room.
        await self.join(room.room_id)

        # Flag room as direct chat.
        await self.room_put_state(
            room_id=room.room_id,
            event_type=self._flags_key,
            content={"m.direct": 1},
        )

        # Get profile and add user to list of known users if required.
        resp = await self.get_profile(event.sender)
        if isinstance(resp, ProfileGetResponse):
            self._user_service.add_known_user(
                event.sender, resp.displayname, room.room_id
            )

    async def _cb_invite_name_event(
        self, _room: MatrixInvitedRoom, _event: InviteNameEvent
    ) -> None:
        """Handle InviteNameEvents."""

    async def _cb_room_create_event(
        self, _room: MatrixRoom, _event: RoomCreateEvent
    ) -> None:
        """Handle RoomCreateEvents."""

    async def _cb_key_verification_event(self, event: KeyVerificationEvent) -> None:
        """Handle key verification events."""

    async def _cb_room_key_event(self, _event: RoomKeyEvent) -> None:
        """Handle RoomKeyEvents."""

    async def _cb_room_key_request(
        self, _room: MatrixRoom, _event: RoomKeyRequest
    ) -> None:
        """Handle RoomKeyRequests."""

    async def _validate_message(self, room: MatrixRoom, message) -> bool:
        """Validate an incoming message"""
        # Only process messages from direct chats for now.
        # And ignore the assistant's messages, otherwise it
        # will create a message loop.
        is_direct = await self._is_direct_message(room.room_id)
        if message.sender == self.user_id or not is_direct:
            return False

        # Verify user devices.
        self.verify_user_devices(message.sender)

        # Set the room read marker to indicate that the assistant has read the
        # message.
        await self.room_read_markers(room.room_id, message.event_id, message.event_id)

        return True

    async def _cb_room_message(self, room: MatrixRoom, message: RoomMessage) -> None:
        """Handle RoomMessage."""
        # This callback is not for text messages.
        if isinstance(message, RoomMessageText):
            return

        # Validate message before proceeding.
        if not await self._validate_message(room, message):
            return

        hits: int = 0
        message_handlers = self._messaging_service.mh_extensions
        for handler in message_handlers:
            if handler.platforms == [] or "matrix" in handler.platforms:
                # Handle audio messages.
                if (
                    isinstance(message, RoomEncryptedAudio)
                    and "audio" in handler.message_types
                ):
                    await asyncio.gather(
                        asyncio.create_task(
                            handler.handle_message(
                                room_id=room.room_id,
                                sender=message.sender,
                                message=message,
                            )
                        )
                    )
                    hits += 1

                # Handle file messages.
                if (
                    isinstance(message, RoomEncryptedFile)
                    and "file" in handler.message_types
                ):
                    await asyncio.gather(
                        asyncio.create_task(
                            handler.handle_message(
                                room_id=room.room_id,
                                sender=message.sender,
                                message=message,
                            )
                        )
                    )
                    hits += 1

                # Handle image messages.
                if (
                    isinstance(message, RoomEncryptedImage)
                    and "image" in handler.message_types
                ):
                    await asyncio.gather(
                        asyncio.create_task(
                            handler.handle_message(
                                room_id=room.room_id,
                                sender=message.sender,
                                message=message,
                            )
                        )
                    )
                    hits += 1

                # Handle video messages.
                if (
                    isinstance(message, RoomEncryptedVideo)
                    and "video" in handler.message_types
                ):
                    await asyncio.gather(
                        asyncio.create_task(
                            handler.handle_message(
                                room_id=room.room_id,
                                sender=message.sender,
                                message=message,
                            )
                        )
                    )
                    hits += 1

        if hits == 0:
            await self._send_text_message(
                room_id=room.room_id,
                body="Unsupported message type.",
            )

    async def _cb_room_message_text(
        self, room: MatrixRoom, message: RoomMessageText
    ) -> None:
        """Handle RoomMessageText."""
        # Validate message before proceeding.
        if not await self._validate_message(room, message):
            return

        # Allow the messaging service to process the message.
        response = await self._messaging_service.handle_text_message(
            "matrix",
            room.room_id,
            message.sender,
            message.body,
        )

        if response != "":
            # Send assistant response to the user.
            self._logging_gateway.debug("Send response to user.")
            await self._send_text_message(room_id=room.room_id, body=response)

    async def _cb_room_member_event(
        self, _room: MatrixRoom, _event: RoomMemberEvent
    ) -> None:
        """Handle RoomMemberEvents."""

    async def _cb_tag_event(self, _event: TagEvent) -> None:
        """Handle TagEvents."""

    # Responses
    async def _cb_sync_response(self, resp: SyncResponse):
        """Handle SyncResponses."""
        self._keyval_storage_gateway.put(self._sync_key, resp.next_batch)

    ## Utilities.
    async def _is_direct_message(self, room_id: str) -> bool:
        """Indicate if the given room was flagged as a 1:1 chat."""
        room_state = await self.room_get_state(room_id)
        flags: list[dict[str, dict[str, int]]] = [
            x for x in room_state.events if x["type"] == self._flags_key
        ]
        return len(flags) > 0 and "m.direct" in flags[0].get("content").keys()

    async def _send_text_message(self, room_id: str, body: str) -> None:
        try:
            await self.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": body,
                },
            )
        except (SendRetryError, LocalProtocolError, OlmUnverifiedDeviceError):
            self._logging_gateway.warning(
                "DefaultMatrixClient: Error sending text message."
            )
            traceback.print_exc()

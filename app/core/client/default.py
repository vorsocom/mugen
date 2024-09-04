"""Provides an implementation of the nio.AsyncClient."""

__all__ = ["DefaultAsyncClient"]

import asyncio
import json
import pickle
import sys
import traceback
from types import SimpleNamespace
from typing import Coroutine

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
    RoomMessageText,
    RoomMemberEvent,
    SendRetryError,
    SyncResponse,
    TagEvent,
)

from nio.api import _FilterT
from nio.client.base_client import logged_in
from nio.exceptions import OlmUnverifiedDeviceError

from app.core.contract.ipc_service import IIPCService
from app.core.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.core.contract.logging_gateway import ILoggingGateway
from app.core.contract.messaging_service import IMessagingService
from app.core.contract.user_service import IUserService

FLAGS_KEY: str = "m.agent_flags"

KNOWN_DEVICES_LIST_KEY: str = "known_devices_list"


# pylint: disable=too-many-instance-attributes
class DefaultAsyncClient(AsyncClient):
    """A custom implementation of nio.AsyncClient."""

    _ipc_callback: Coroutine

    _sync_key: str = "matrix_client_sync_next_batch"

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        di_config: dict = None,
        ipc_queue: asyncio.Queue = None,
        ipc_service: IIPCService = None,
        keyval_storage_gateway: IKeyValStorageGateway = None,
        logging_gateway: ILoggingGateway = None,
        messaging_service: IMessagingService = None,
        user_service: IUserService = None,
    ):
        self._config = SimpleNamespace(**di_config)
        super().__init__(
            homeserver=self._config.matrix_homeserver,
            user=self._config.matrix_client_user,
            store_path=self._config.matrix_olm_store_path,
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
        if self._keyval_storage_gateway.get("client_access_token") is None:
            # Load password and device name from storage.
            pw = self._config.matrix_client_password
            dn = self._config.matrix_client_device_name

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
        self._logging_gateway.info("Login using saved credentials.")
        # open the file in read-only mode.
        self.access_token = self._keyval_storage_gateway.get("client_access_token")
        self.device_id = self._keyval_storage_gateway.get("client_device_id")
        self.user_id = self._keyval_storage_gateway.get("client_user_id")
        self.load_store()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Finalisation."""
        try:
            await self.client_session.close()
        except AttributeError:
            ...

    @property
    def sync_token(self) -> str:
        """Get the key to access the sync key from persistent storage."""
        return self._keyval_storage_gateway.get(self._sync_key)

    # pylint: disable=too-many-arguments,too-many-locals
    @logged_in
    async def sync_forever(
        self,
        timeout: int | None = None,
        sync_filter: _FilterT = None,
        since: str | None = None,
        full_state: bool | None = None,
        loop_sleep_time: int | None = None,
        first_sync_filter: _FilterT = None,
        set_presence: str | None = None,
    ):
        """Continuously sync with the configured homeserver.

        This method calls the sync method in a loop. To react to events event
        callbacks should be configured.

        The loop also makes sure to handle other required requests between
        syncs, including to_device messages and sending encryption keys if
        required. To react to the responses a response callback should be
        added.

        Args:
            timeout (int, optional): The maximum time that the server should
                wait for new events before it should return the request
                anyways, in milliseconds.
                If ``0``, no timeout is applied.
                If ``None``, ``AsyncClient.config.request_timeout`` is used.
                In any case, ``0`` is always used for the first sync.
                If a timeout is applied and the server fails to return after
                15 seconds of expected timeout,
                the client will timeout by itself.

            sync_filter (Union[None, str, Dict[Any, Any]):
                A filter ID that can be obtained from
                ``AsyncClient.upload_filter()`` (preferred),
                or filter dict that should be used for sync requests.

            full_state (bool, optional): Controls whether to include the full
                state for all rooms the user is a member of. If this is set to
                true, then all state events will be returned, even if since is
                non-empty. The timeline will still be limited by the since
                parameter. This argument will be used only for the first sync
                request.

            since (str, optional): A token specifying a point in time where to
                continue the sync from. Defaults to the last sync token we
                received from the server using this API call. This argument
                will be used only for the first sync request, the subsequent
                sync requests will use the token from the last sync response.

            loop_sleep_time (int, optional): The sleep time, if any, between
                successful sync loop iterations in milliseconds.

            first_sync_filter (Union[None, str, Dict[Any, Any]):
                A filter ID that can be obtained from
                ``AsyncClient.upload_filter()`` (preferred),
                or filter dict to use for the first sync request only.
                If `None` (default), the `sync_filter` parameter's value
                is used.
                To have no filtering for the first sync regardless of
                `sync_filter`'s value, pass `{}`.

            set_presence (str, optional): The presence state.
                One of: ["online", "offline", "unavailable"]
        """

        first_sync = True

        while True:
            try:
                use_filter = first_sync_filter if first_sync else sync_filter
                use_timeout = 0 if first_sync else timeout

                tasks = []

                # Make sure that if this is our first sync that the sync happens
                # before the other requests, this helps to ensure that after one
                # fired synced event the state is indeed fully synced.
                if first_sync:
                    presence = set_presence or self._presence
                    sync_response = await self.sync(
                        use_timeout, use_filter, since, full_state, presence
                    )
                    await self.run_response_callbacks([sync_response])
                else:
                    presence = set_presence or self._presence
                    tasks = [
                        asyncio.ensure_future(coro)
                        for coro in (
                            self.sync(
                                use_timeout, use_filter, since, full_state, presence
                            ),
                            self.send_to_device_messages(),
                        )
                    ]

                if self.should_upload_keys:
                    tasks.append(asyncio.ensure_future(self.keys_upload()))

                if self.should_query_keys:
                    tasks.append(asyncio.ensure_future(self.keys_query()))

                if self.should_claim_keys:
                    tasks.append(
                        asyncio.ensure_future(
                            self.keys_claim(self.get_users_for_key_claiming()),
                        )
                    )

                for response in asyncio.as_completed(tasks):
                    await self.run_response_callbacks([await response])

                # CHANGE: Run IPC callback.
                await self._run_ipc_callback()

                first_sync = False
                full_state = None
                since = None

                self.synced.set()
                self.synced.clear()

                if loop_sleep_time:
                    await asyncio.sleep(loop_sleep_time / 1000)

            except asyncio.CancelledError:
                for task in tasks:
                    task.cancel()

                break

    def cleanup_known_user_devices_list(self) -> None:
        """Clean up known user devices list."""
        self._logging_gateway.debug("Cleaning up known user devices.")
        if self._keyval_storage_gateway.has_key(KNOWN_DEVICES_LIST_KEY):
            known_devices = pickle.loads(
                self._keyval_storage_gateway.get(KNOWN_DEVICES_LIST_KEY, False)
            )
            for user_id in known_devices.keys():
                active_devices = [
                    x.device_id for x in self.device_store.active_user_devices(user_id)
                ]
                self._logging_gateway.debug(f"Active devices: {active_devices}")
                known_devices[user_id] = active_devices

            # Persist changes.
            self._keyval_storage_gateway.put(
                KNOWN_DEVICES_LIST_KEY, pickle.dumps(known_devices)
            )

    def trust_known_user_devices(self) -> None:
        """Trust all known user devices."""
        self._logging_gateway.debug("Trusting all known user devices.")
        if self._keyval_storage_gateway.has_key(KNOWN_DEVICES_LIST_KEY):
            known_devices = pickle.loads(
                self._keyval_storage_gateway.get(KNOWN_DEVICES_LIST_KEY, False)
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
                self.verify_device(olm_device)

                # Persist changes to the known devices list.
                self._keyval_storage_gateway.put(
                    KNOWN_DEVICES_LIST_KEY, pickle.dumps(known_devices)
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
        allowed_domains = self._config.gloria_allowed_domains.split("|")
        if event.sender.split(":")[1] not in allowed_domains:
            await self.room_leave(room.room_id)
            self._logging_gateway.warning(
                "InviteMemberEvent: Rejected invitation. Reason: Domain"
                f" not allowed. ({event.sender})"
            )
            return

        # If the assistant is in limited-beta mode, only process invites from the
        # list of selected beta users.
        if self._config.gloria_limited_beta.lower() in (
            "true",
            "1",
        ):
            beta_users: list = json.loads(self._config.gloria_limited_beta_users)
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
            event_type=FLAGS_KEY,
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

    async def _cb_room_message_text(
        self, room: MatrixRoom, message: RoomMessageText
    ) -> None:
        """Handle RoomMessageTexts."""
        # Only process messages from direct chats for now.
        # And ignore the assistant's messages, otherwise it
        # will create a message loop.
        is_direct = await self._is_direct_message(room.room_id)
        if message.sender == self.user_id or not is_direct:
            return

        # Verify user devices.
        self.verify_user_devices(message.sender)

        # Set the room read marker to indicate that the assistant has read the
        # message.
        await self.room_read_markers(room.room_id, message.event_id, message.event_id)

        # Allow the messaging service to process the message.
        response = await self._messaging_service.handle_text_message(
            room.room_id,
            message.sender,
            message.body,
        )

        if response != "":
            # Send assistant response to the user.
            self._logging_gateway.debug("Send response to user.")
            try:
                await self.room_send(
                    room_id=room.room_id,
                    message_type="m.room.message",
                    content={
                        "msgtype": "m.text",
                        "body": response,
                    },
                )
            except (SendRetryError, LocalProtocolError, OlmUnverifiedDeviceError):
                self._logging_gateway.warning(
                    "matrix_platform_gateway: Error sending text message."
                )
                traceback.print_exc()

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
            x for x in room_state.events if x["type"] == FLAGS_KEY
        ]
        return len(flags) > 0 and "m.direct" in flags[0].get("content").keys()

    async def _run_ipc_callback(self) -> None:
        """Run the configured IPC callback."""
        while not self._ipc_queue.empty():
            payload = await self._ipc_queue.get()
            asyncio.create_task(self._ipc_service.handle_ipc_request(payload))
            self._ipc_queue.task_done()

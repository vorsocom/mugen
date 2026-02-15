"""Provides an implementation of IMatrixClient."""

__all__ = ["DefaultMatrixClient"]

from io import BytesIO

import json
import mimetypes
import os
import tempfile
import traceback
from types import SimpleNamespace
from typing import Coroutine

import aiofiles

from nio import (
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

import nio.crypto
from nio.exceptions import OlmUnverifiedDeviceError
from nio.responses import UploadResponse, DiskDownloadResponse

from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.user import IUserService


class DefaultMatrixClient(  # pylint: disable=too-many-instance-attributes
    IMatrixClient
):
    """A custom implementation of IMatrixClient."""

    _callback_skip_reason_dm_scope: str = "unsupported_dm_scope"

    _device_trust_mode_allowlist: str = "allowlist"

    _device_trust_mode_permissive: str = "permissive"

    _device_trust_mode_strict_known: str = "strict_known"

    _flags_key: str = "m.agent_flags"

    _ipc_callback: Coroutine

    _known_devices_list_key: str = "known_devices_list"

    _sync_key: str = "matrix_client_sync_next_batch"

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        config: SimpleNamespace = None,
        ipc_service: IIPCService = None,
        keyval_storage_gateway: IKeyValStorageGateway = None,
        logging_gateway: ILoggingGateway = None,
        messaging_service: IMessagingService = None,
        user_service: IUserService = None,
    ):
        self._config = config
        super().__init__(
            homeserver=self._config.matrix.homeserver,
            user=self._config.matrix.client.user,
            store_path=os.path.join(
                self._config.basedir,
                self._config.matrix.storage.olm.path,
            ),
        )
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

        # To-device Events.
        self.add_to_device_callback(
            self._cb_key_verification_event, KeyVerificationEvent
        )
        self.add_to_device_callback(self._cb_room_key_event, RoomKeyEvent)
        self.add_to_device_callback(self._cb_room_key_request, RoomKeyRequest)

        # Responses.
        self.add_response_callback(self._cb_sync_response, SyncResponse)

    async def __aenter__(self) -> "DefaultMatrixClient":
        """Initialisation."""
        self._logging_gateway.debug("DefaultMatrixClient.__aenter__")
        if self._keyval_storage_gateway.get("client_access_token") is None:
            # Load password and device name from storage.
            pw = self._config.matrix.client.password
            dn = self._config.matrix.client.device

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
                self.access_token = resp.access_token
                self.device_id = resp.device_id
                self.user_id = resp.user_id
                self.load_store()
                return self
            else:
                self._logging_gateway.error("Password login failed.")
                raise RuntimeError("Matrix password login failed.")

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

    def _load_known_devices(self) -> dict[str, list[str]]:
        if not self._keyval_storage_gateway.has_key(self._known_devices_list_key):
            return {}

        payload = self._keyval_storage_gateway.get(self._known_devices_list_key, False)
        if isinstance(payload, bytes):
            try:
                payload = payload.decode("utf-8")
            except UnicodeDecodeError:
                self._logging_gateway.warning("Invalid known devices payload; resetting.")
                return {}
        try:
            loaded = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            self._logging_gateway.warning("Invalid known devices payload; resetting.")
            return {}

        if not isinstance(loaded, dict):
            self._logging_gateway.warning(
                "Known devices payload type mismatch; resetting."
            )
            return {}

        known_devices: dict[str, list[str]] = {}
        for user_id, devices in loaded.items():
            if not isinstance(devices, list):
                continue
            known_devices[user_id] = [str(device_id) for device_id in devices]
        return known_devices

    def _save_known_devices(self, known_devices: dict[str, list[str]]) -> None:
        self._keyval_storage_gateway.put(
            self._known_devices_list_key,
            json.dumps(known_devices),
        )

    def cleanup_known_user_devices_list(self) -> None:
        """Clean up known user devices list."""
        self._logging_gateway.debug("Cleaning up known user devices.")
        known_devices = self._load_known_devices()
        if not known_devices:
            return

        for user_id in known_devices.keys():
            active_devices = [
                x.device_id for x in self.device_store.active_user_devices(user_id)
            ]
            self._logging_gateway.debug(f"Active devices: {active_devices}")
            known_devices[user_id] = active_devices

        # Persist changes.
        self._save_known_devices(known_devices)

    def trust_known_user_devices(self) -> None:
        """Trust all known user devices."""
        self._logging_gateway.debug("Trusting all known user devices.")
        known_devices = self._load_known_devices()
        for user_id in known_devices.keys():
            self._logging_gateway.debug(f"User: {user_id}")
            for device_id, olm_device in self.device_store[user_id].items():
                if device_id in known_devices[user_id]:
                    # Verify the device.
                    self._logging_gateway.debug(f"Trusting {device_id}.")
                    self.verify_device(olm_device)

    def _resolve_device_trust_mode(self) -> str:
        mode = getattr(
            getattr(
                getattr(
                    getattr(self._config, "matrix", SimpleNamespace()),
                    "security",
                    SimpleNamespace(),
                ),
                "device_trust",
                SimpleNamespace(),
            ),
            "mode",
            self._device_trust_mode_strict_known,
        )
        if not isinstance(mode, str):
            self._logging_gateway.warning(
                "Matrix device trust mode invalid; using strict_known."
            )
            return self._device_trust_mode_strict_known

        mode = mode.strip().lower()
        supported_modes = {
            self._device_trust_mode_strict_known,
            self._device_trust_mode_allowlist,
            self._device_trust_mode_permissive,
        }
        if mode in supported_modes:
            return mode

        self._logging_gateway.warning(
            f"Matrix device trust mode unsupported ({mode}); using strict_known."
        )
        return self._device_trust_mode_strict_known

    def _resolve_device_trust_allowlist(self) -> dict[str, set[str]]:
        allowlist = getattr(
            getattr(
                getattr(
                    getattr(self._config, "matrix", SimpleNamespace()),
                    "security",
                    SimpleNamespace(),
                ),
                "device_trust",
                SimpleNamespace(),
            ),
            "allowlist",
            [],
        )

        if not isinstance(allowlist, list):
            self._logging_gateway.warning(
                "Matrix device trust allowlist invalid; expected list."
            )
            return {}

        parsed_allowlist: dict[str, set[str]] = {}
        for entry in allowlist:
            user_id = None
            device_ids = None

            if isinstance(entry, dict):
                user_id = entry.get("user_id")
                device_ids = entry.get("device_ids")
            elif isinstance(entry, SimpleNamespace):
                user_id = getattr(entry, "user_id", None)
                device_ids = getattr(entry, "device_ids", None)

            if not isinstance(user_id, str) or not isinstance(device_ids, list):
                continue

            if user_id not in parsed_allowlist:
                parsed_allowlist[user_id] = set()
            parsed_allowlist[user_id].update(
                [str(device_id) for device_id in device_ids]
            )

        return parsed_allowlist

    def _log_untrusted_device(
        self,
        user_id: str,
        device_id: str,
        mode: str,
        reason: str,
    ) -> None:
        self._logging_gateway.warning(
            "Matrix device not trusted."
            f" user_id={user_id}"
            f" device_id={device_id}"
            f" mode={mode}"
            f" reason={reason}"
        )

    @staticmethod
    def _parse_sender_domain(sender_id: str) -> str | None:
        if not isinstance(sender_id, str):
            return None

        local_part, separator, domain_part = sender_id.partition(":")
        if separator == "" or not local_part.startswith("@") or domain_part.strip() == "":
            return None

        return domain_part

    def _direct_invites_only(self) -> bool:
        return bool(
            getattr(
                getattr(getattr(self._config, "matrix", SimpleNamespace()), "invites", None),
                "direct_only",
                True,
            )
        )

    def verify_user_devices(self, user_id: str) -> None:
        """Verify all of a user's devices."""
        self._logging_gateway.debug(f"Verifying all user devices ({user_id}).")
        mode = self._resolve_device_trust_mode()
        allowlist = {}
        if mode == self._device_trust_mode_allowlist:
            allowlist = self._resolve_device_trust_allowlist()

        known_devices = self._load_known_devices()
        for device_id, olm_device in self.device_store.get(user_id, {}).items():
            self._logging_gateway.debug(f"Found {device_id}.")
            if mode == self._device_trust_mode_strict_known:
                if device_id in known_devices.get(user_id, []):
                    self._logging_gateway.debug(f"Verifying {device_id}.")
                    self.verify_device(olm_device)
                else:
                    self._log_untrusted_device(
                        user_id=user_id,
                        device_id=device_id,
                        mode=mode,
                        reason="unknown_device",
                    )
                continue

            if mode == self._device_trust_mode_allowlist:
                if device_id in allowlist.get(user_id, set()):
                    self._logging_gateway.debug(f"Verifying {device_id}.")
                    self.verify_device(olm_device)
                else:
                    self._log_untrusted_device(
                        user_id=user_id,
                        device_id=device_id,
                        mode=mode,
                        reason="not_in_allowlist",
                    )
                continue

            # Ensure the list contains an entry for the user.
            if user_id not in known_devices.keys():
                known_devices[user_id] = []

            # If the device is not already in the known devices list for the user.
            if device_id not in known_devices[user_id]:
                # Add the device id to the list of known devices for the user.
                known_devices[user_id].append(device_id)

                # Verify the device.
                self._logging_gateway.debug(f"Verifying {device_id}.")
                self.verify_device(olm_device)

                # Persist changes to the known devices list.
                self._save_known_devices(known_devices)

    def _log_skipped_callback(
        self,
        callback_name: str,
        event: object = None,
        reason: str = _callback_skip_reason_dm_scope,
    ) -> None:
        event_type = type(event).__name__ if event is not None else "UnknownEvent"
        self._logging_gateway.debug(
            "Matrix callback skipped."
            f" callback={callback_name}"
            f" event={event_type}"
            f" reason={reason}"
        )

    ## Callbacks.
    # Events
    async def _cb_megolm_event(self, _room: MatrixRoom, _event: MegolmEvent) -> None:
        """Handle MegolmEvents."""
        self._log_skipped_callback("_cb_megolm_event", event=_event)

    async def _cb_invite_alias_event(self, _event: InviteAliasEvent) -> None:
        """Handle InviteAliasEvents."""
        self._log_skipped_callback("_cb_invite_alias_event", event=_event)

    async def _cb_invite_member_event(
        self, room: MatrixInvitedRoom, event: InviteMemberEvent
    ) -> None:
        """Handle InviteMemberEvents."""
        event_content = event.content if isinstance(event.content, dict) else {}

        # Filter out events that do not have membership set to invite.
        membership = event_content.get("membership")
        if membership is not None and membership != "invite":
            return

        # Only process invites from allowed domains.
        # Federated servers need to be in the allowed domains list for their users
        # to initiate conversations with the assistant.
        allowed_domains: list = self._config.matrix.domains.allowed
        denied_domains: list = self._config.matrix.domains.denied
        sender_domain = self._parse_sender_domain(event.sender)
        if sender_domain is None:
            await self.room_leave(room.room_id)
            self._logging_gateway.warning(
                "InviteMemberEvent: Rejected invitation. Reason: Malformed sender."
                f" ({event.sender})"
            )
            return

        if sender_domain not in allowed_domains or sender_domain in denied_domains:
            await self.room_leave(room.room_id)
            self._logging_gateway.warning(
                "InviteMemberEvent: Rejected invitation. Reason: Domain"
                f" not allowed. ({event.sender})"
            )
            return

        # If the assistant is in limited-beta mode, only process invites from the
        # list of selected beta users.
        if self._config.mugen.beta.active:
            beta_users: list = self._config.matrix.beta.users
            if event.sender not in beta_users:
                await self.room_leave(room.room_id)
                self._logging_gateway.warning(
                    "InviteMemberEvent: Rejected invitation. Reason:"
                    f" Non-beta user. ({event.sender})"
                )
                return

        # Only accept invites to Direct Messages for now.
        if self._direct_invites_only():
            is_direct = event_content.get("is_direct")
            if is_direct is not True:
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
        self._log_skipped_callback("_cb_invite_name_event", event=_event)

    async def _cb_room_create_event(
        self, _room: MatrixRoom, _event: RoomCreateEvent
    ) -> None:
        """Handle RoomCreateEvents."""
        self._log_skipped_callback("_cb_room_create_event", event=_event)

    async def _cb_key_verification_event(self, event: KeyVerificationEvent) -> None:
        """Handle key verification events."""
        self._log_skipped_callback("_cb_key_verification_event", event=event)

    async def _cb_room_key_event(self, _event: RoomKeyEvent) -> None:
        """Handle RoomKeyEvents."""
        self._log_skipped_callback("_cb_room_key_event", event=_event)

    async def _cb_room_key_request(
        self, _room: MatrixRoom, _event: RoomKeyRequest
    ) -> None:
        """Handle RoomKeyRequests."""
        self._log_skipped_callback("_cb_room_key_request", event=_event)

    async def _validate_message(self, room: MatrixRoom, message) -> bool:
        """Validate an incoming message"""
        sender_id = getattr(message, "sender", None)
        if self._parse_sender_domain(sender_id) is None:
            self._logging_gateway.warning(
                "RoomMessage: Rejected message. Reason: Malformed sender."
                f" ({sender_id})"
            )
            return False

        # Only process messages from direct chats for now.
        # And ignore the assistant's messages, otherwise it
        # will create a message loop.
        is_direct = await self._is_direct_message(room.room_id)
        if sender_id == self.user_id:
            return False
        if not is_direct:
            self._logging_gateway.debug(
                "RoomMessage: Ignored message. Reason: Room not marked direct."
                f" ({room.room_id})"
            )
            return False

        # Verify user devices.
        self.verify_user_devices(sender_id)

        # Set the room read marker to indicate that the assistant has read the
        # message.
        await self.room_read_markers(room.room_id, message.event_id, message.event_id)

        return True

    async def _cb_room_message(self, room: MatrixRoom, message: RoomMessage) -> None:
        """Handle RoomMessage."""
        # Validate message before proceeding.
        if not await self._validate_message(room, message):
            return

        message_responses: list[dict] = []

        # Handle audio messages.
        if isinstance(message, RoomEncryptedAudio):
            get_media = await self._download_file(
                message.source["content"]["file"],
                message.source["content"]["info"],
            )
            if get_media:
                message_responses = await self._messaging_service.handle_audio_message(
                    platform="matrix",
                    room_id=room.room_id,
                    sender=message.sender,
                    message={
                        "message": message,
                        "file": get_media,
                    },
                )
        # Handle file messages.
        elif isinstance(message, RoomEncryptedFile):
            get_media = await self._download_file(
                message.source["content"]["file"],
                message.source["content"]["info"],
            )
            if get_media:
                message_responses = await self._messaging_service.handle_file_message(
                    platform="matrix",
                    room_id=room.room_id,
                    sender=message.sender,
                    message={
                        "message": message,
                        "file": get_media,
                    },
                )
        # Handle image messages.
        elif isinstance(message, RoomEncryptedImage):
            get_media = await self._download_file(
                message.source["content"]["file"],
                message.source["content"]["info"],
            )
            if get_media:
                message_responses = await self._messaging_service.handle_image_message(
                    platform="matrix",
                    room_id=room.room_id,
                    sender=message.sender,
                    message={
                        "message": message,
                        "file": get_media,
                    },
                )
        # Handle text messages.
        elif isinstance(message, RoomMessageText):
            message_responses = await self._messaging_service.handle_text_message(
                platform="matrix",
                room_id=room.room_id,
                sender=message.sender,
                message=message.body,
            )
        # Handle video messages.
        elif isinstance(message, RoomEncryptedVideo):
            get_media = await self._download_file(
                message.source["content"]["file"],
                message.source["content"]["info"],
            )
            if get_media:
                message_responses = await self._messaging_service.handle_video_message(
                    platform="matrix",
                    room_id=room.room_id,
                    sender=message.sender,
                    message={
                        "message": message,
                        "file": get_media,
                    },
                )

        await self._process_message_responses(
            room_id=room.room_id,
            message_responses=message_responses,
        )

    async def _cb_room_member_event(
        self, _room: MatrixRoom, _event: RoomMemberEvent
    ) -> None:
        """Handle RoomMemberEvents."""
        self._log_skipped_callback("_cb_room_member_event", event=_event)

    async def _cb_tag_event(self, _event: TagEvent) -> None:
        """Handle TagEvents."""
        self._log_skipped_callback("_cb_tag_event", event=_event)

    # Responses
    async def _cb_sync_response(self, resp: SyncResponse):
        """Handle SyncResponses."""
        self._keyval_storage_gateway.put(self._sync_key, resp.next_batch)

    ## Utilities.
    async def _is_direct_message(self, room_id: str) -> bool:
        """Indicate if the given room was flagged as a 1:1 chat."""
        room_state = await self.room_get_state(room_id)
        events = getattr(room_state, "events", [])
        if not isinstance(events, list):
            return False

        for event in events:
            if not isinstance(event, dict):
                continue
            if event.get("type") != self._flags_key:
                continue
            content = event.get("content")
            if not isinstance(content, dict):
                continue
            if content.get("m.direct") in [1, True]:
                return True

        return False

    async def _process_message_responses(
        self, room_id: str, message_responses: list[dict]
    ) -> None:

        self._logging_gateway.debug("Send responses to user.")

        for response in message_responses:
            match response["type"]:
                case "audio":
                    await self._send_audio_message(
                        room_id=room_id,
                        file=response["file"],
                        audio_info=response["info"],
                    )
                case "file":
                    await self._send_file_message(
                        room_id=room_id,
                        file=response["file"],
                    )
                case "image":
                    await self._send_image_message(
                        room_id=room_id,
                        file=response["file"],
                        image_info=response["info"],
                    )
                case "text":
                    await self._send_text_message(
                        room_id=room_id,
                        body=response["content"],
                    )
                case "video":
                    await self._send_video_message(
                        room_id=room_id,
                        file=response["file"],
                        video_info=response["info"],
                    )
                case _:
                    pass

    async def _send_audio_message(
        self,
        room_id: str,
        file: dict,
        audio_info: dict,
    ) -> None:
        try:
            resp, encryption_keys = await self._upload_file(file)
            if resp is None:
                return

            if isinstance(resp, UploadResponse):
                await self.room_send(
                    room_id=room_id,
                    message_type="m.room.message",
                    content={
                        "msgtype": "m.audio",
                        "file": {
                            "url": resp.content_uri,
                            "hashes": encryption_keys["hashes"],
                            "iv": encryption_keys["iv"],
                            "key": encryption_keys["key"],
                            "v": encryption_keys["v"],
                        },
                        "body": file["name"],
                        "info": {
                            "mimetype": file["type"],
                            "size": file["size"],
                            "duration": audio_info["duration"],
                        },
                    },
                )

        except (SendRetryError, LocalProtocolError, OlmUnverifiedDeviceError):
            self._logging_gateway.warning(
                "DefaultMatrixClient: Error sending audio message."
            )
            traceback.print_exc()

    async def _send_file_message(
        self,
        room_id: str,
        file: dict,
    ) -> None:
        try:
            resp, encryption_keys = await self._upload_file(file)
            if resp is None:
                return

            if isinstance(resp, UploadResponse):
                await self.room_send(
                    room_id=room_id,
                    message_type="m.room.message",
                    content={
                        "msgtype": "m.file",
                        "file": {
                            "url": resp.content_uri,
                            "hashes": encryption_keys["hashes"],
                            "iv": encryption_keys["iv"],
                            "key": encryption_keys["key"],
                            "v": encryption_keys["v"],
                        },
                        "body": file["name"],
                        "info": {
                            "mimetype": file["type"],
                            "size": file["size"],
                        },
                    },
                )

        except (SendRetryError, LocalProtocolError, OlmUnverifiedDeviceError):
            self._logging_gateway.warning(
                "DefaultMatrixClient: Error sending file message."
            )
            traceback.print_exc()

    async def _send_image_message(
        self,
        room_id: str,
        file: dict,
        image_info: dict,
    ) -> None:
        try:
            resp, encryption_keys = await self._upload_file(file)
            if resp is None:
                return

            if isinstance(resp, UploadResponse):
                await self.room_send(
                    room_id=room_id,
                    message_type="m.room.message",
                    content={
                        "msgtype": "m.image",
                        "file": {
                            "url": resp.content_uri,
                            "hashes": encryption_keys["hashes"],
                            "iv": encryption_keys["iv"],
                            "key": encryption_keys["key"],
                            "v": encryption_keys["v"],
                        },
                        "body": file["name"],
                        "info": {
                            "mimetype": file["type"],
                            "size": file["size"],
                            "h": image_info["height"],
                            "w": image_info["width"],
                        },
                    },
                )

        except (SendRetryError, LocalProtocolError, OlmUnverifiedDeviceError):
            self._logging_gateway.warning(
                "DefaultMatrixClient: Error sending image message."
            )
            traceback.print_exc()

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

    async def _send_video_message(
        self,
        room_id: str,
        file: dict,
        video_info: dict,
    ) -> None:
        try:
            resp, encryption_keys = await self._upload_file(file)
            if resp is None:
                return

            if isinstance(resp, UploadResponse):
                await self.room_send(
                    room_id=room_id,
                    message_type="m.room.message",
                    content={
                        "msgtype": "m.video",
                        "file": {
                            "url": resp.content_uri,
                            "hashes": encryption_keys["hashes"],
                            "iv": encryption_keys["iv"],
                            "key": encryption_keys["key"],
                            "v": encryption_keys["v"],
                        },
                        "body": file["name"],
                        "info": {
                            "mimetype": file["type"],
                            "size": file["size"],
                            "duration": video_info["duration"],
                            "h": video_info["height"],
                            "w": video_info["width"],
                        },
                    },
                )
        except (SendRetryError, LocalProtocolError, OlmUnverifiedDeviceError):
            self._logging_gateway.warning(
                "DefaultMatrixClient: Error sending video message."
            )
            traceback.print_exc()

    async def _download_file(self, file: dict, info: dict) -> str | None:
        # Guess extension using mimetype.
        extension = mimetypes.guess_extension(info["mimetype"])

        # Successfully guessed extension.
        if extension:
            # Use a tempfile for savng encrypted file.
            with tempfile.NamedTemporaryFile(suffix=extension) as tf:

                # Download the encrypted file.
                resp = await self.download(
                    file["url"],
                    save_to=tf.name,
                )

                # Download successful.
                if isinstance(resp, DiskDownloadResponse):

                    # Open ecrypted file for reading.
                    with open(tf.name, "rb") as tfb:

                        # Decrypt file.
                        decrypted_file = nio.crypto.decrypt_attachment(
                            tfb.read(),
                            key=file["key"]["k"],
                            hash=file["hashes"]["sha256"],
                            iv=file["iv"],
                        )

                        # Use tempfile for saving decrypted file.
                        with tempfile.NamedTemporaryFile(
                            suffix=extension, delete=False
                        ) as df:

                            # Open tempfile to save decrypted bytes.
                            with open(df.name, "wb"):
                                df.write(decrypted_file)
                                return df.name

    async def _upload_file(self, file: dict):
        resp = None
        maybe_keys = None

        if isinstance(file["uri"], BytesIO):
            resp, maybe_keys = await self._upload_in_memory_file(file)
        else:
            resp, maybe_keys = await self._upload_disk_file(file)

        return resp, maybe_keys

    async def _upload_in_memory_file(
        self,
        file: dict,
        encrypt: bool = True,
    ):
        return await self.upload(
            file["uri"],
            content_type=file["type"],
            filename=file["name"],
            filesize=file["size"],
            encrypt=encrypt,
        )

    async def _upload_disk_file(
        self,
        file: dict,
        encrypt: bool = True,
    ):
        async with aiofiles.open(file["uri"], "r+b") as f:
            return await self.upload(
                f,
                content_type=file["type"],
                filename=file["name"],
                filesize=file["size"],
                encrypt=encrypt,
            )

"""
Provides class to pass client to callback methods.
"""

__all__ = ["Callbacks", "SYNC_KEY"]

from typing import Mapping

from nio import (
    AsyncClient,
    InviteAliasEvent,
    InviteMemberEvent,
    InviteNameEvent,
    MatrixInvitedRoom,
    MatrixRoom,
    MegolmEvent,
    ProfileGetResponse,
    RoomCreateEvent,
    RoomKeyEvent,
    RoomKeyRequest,
    RoomMessageText,
    RoomMemberEvent,
    SyncResponse,
    TagEvent,
)

from app.contract.ipc_service import IIPCService
from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.logging_gateway import ILoggingGateway
from app.contract.messaging_service import IMessagingService
from app.contract.user_service import IUserService

FLAGS_KEY: str = "m.agent_flags"

SYNC_KEY: str = "matrix_client_sync_next_batch"


class Callbacks:
    """Class to pass client to callback methods."""

    def __init__(
        self,
        client: AsyncClient,
        ipc_service: IIPCService,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
        messaging_service: IMessagingService,
        user_service: IUserService,
    ) -> None:
        """Store AsyncClient"""
        self._client = client
        self._ipc_service = ipc_service
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._messaging_service = messaging_service
        self._user_service = user_service

    # IPC
    async def ipc_handler(self, ipc_payload: dict) -> None:
        """Handle IPC events."""
        await self._ipc_service.handle_ipc_request(ipc_payload)

    # Events
    async def megolm_event(self, _room: MatrixRoom, _event: MegolmEvent) -> None:
        """Handle MegolmEvents."""
        self._logging_gateway.debug("MegolmEvent")

    async def invite_alias_event(self, _event: InviteAliasEvent) -> None:
        """Handle InviteAliasEvents."""

    async def invite_member_event(
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
        allowed_domains = self._keyval_storage_gateway.get(
            "gloria_allowed_domains"
        ).split("|")
        if event.sender.split(":")[1] not in allowed_domains:
            await self._client.room_leave(room.room_id)
            self._logging_gateway.warning(
                "callbacks:invite_member_event: Rejected invitation. Reason: Domain"
                f" not allowed. ({event.sender})"
            )
            return

        # If the assistant is in limited-beta mode, only process invites from the
        # list of selected beta users.
        if self._keyval_storage_gateway.get("gloria_limited_beta").lower() in (
            "true",
            "1",
        ):
            beta_users = self._keyval_storage_gateway.get(
                "gloria_limited_beta_users"
            ).split("|")
            if event.sender not in beta_users:
                await self._client.room_leave(room.room_id)
                self._logging_gateway.warning(
                    "callbacks:invite_member_event: Rejected invitation. Reason:"
                    f" Non-beta user. ({event.sender})"
                )
                return

        # Only accept invites to Direct Messages for now.
        is_direct = event.content.get("is_direct")
        if is_direct is None:
            await self._client.room_leave(room.room_id)
            self._logging_gateway.warning(
                "callbacks:invite_member_event: Rejected invitation. Reason: Not direct"
                f" message. ({event.sender})"
            )
            return

        # Verify user devices.
        self._user_service.verify_user_devices(event.sender)
        self._user_service.verify_user_devices(self._client.user_id)

        # Join room.
        await self._client.join(room.room_id)

        # Flag room as direct chat.
        await self._client.room_put_state(
            room_id=room.room_id,
            event_type=FLAGS_KEY,
            content={"m.direct": 1},
        )

        # Get profile and add user to list of known users if required.
        resp = await self._client.get_profile(event.sender)
        if isinstance(resp, ProfileGetResponse):
            self._user_service.add_known_user(
                event.sender, resp.displayname, room.room_id
            )

    async def invite_name_event(
        self, _room: MatrixInvitedRoom, _event: InviteNameEvent
    ) -> None:
        """Handle InviteNameEvents."""

    async def room_create_event(
        self, _room: MatrixRoom, _event: RoomCreateEvent
    ) -> None:
        """Handle RoomCreateEvents."""

    async def room_key_event(self, _event: RoomKeyEvent) -> None:
        """Handle RoomKeyEvents."""

    async def room_key_request(self, _room: MatrixRoom, _event: RoomKeyRequest) -> None:
        """Handle RoomKeyRequests."""

    async def room_message_text(
        self, room: MatrixRoom, message: RoomMessageText
    ) -> None:
        """Handle RoomMessageTexts."""
        # Only process messages from direct chats for now.
        # And ignore the assistant's messages, otherwise it
        # will create a message loop.
        is_direct = await self.is_direct_message(room.room_id)
        if message.sender == self._client.user_id or not is_direct:
            return

        # Verify user devices.
        self._user_service.verify_user_devices(message.sender)
        self._user_service.verify_user_devices(self._client.user_id)

        # Allow the messaging service to process the message.
        await self._messaging_service.handle_text_message(
            room.room_id,
            message.event_id,
            message.sender,
            message.body,
        )

    async def room_member_event(
        self, _room: MatrixRoom, _event: RoomMemberEvent
    ) -> None:
        """Handle RoomMemberEvents."""

    async def tag_event(self, _event: TagEvent) -> None:
        """Handle TagEvents."""

    # Responses
    async def sync_response(self, resp: SyncResponse):
        """Handle SyncResponses."""
        self._keyval_storage_gateway.put(SYNC_KEY, resp.next_batch)

    # Utilities.
    async def is_direct_message(self, room_id: str) -> bool:
        """Indicate if the given room was flagged as a 1:1 chat."""
        room_state = await self._client.room_get_state(room_id)
        flags: list[Mapping[str, Mapping[str, int]]] = [
            x for x in room_state.events if x["type"] == FLAGS_KEY
        ]
        return len(flags) > 0 and "m.direct" in flags[0].get("content").keys()

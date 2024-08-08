"""
Provides class to pass client to callback methods.
"""

import pickle
from typing import Mapping

from nio import (
    AsyncClient,
    InviteAliasEvent,
    MatrixInvitedRoom,
    InviteMemberEvent,
    InviteNameEvent,
    MatrixRoom,
    RoomMessageText,
    SyncResponse,
    TagEvent,
    RoomCreateEvent,
    ProfileGetResponse,
)

from app.contract.completion_gateway import ICompletionGateway
from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.knowledge_retrieval_gateway import IKnowledgeRetrievalGateway
from app.contract.logging_gateway import ILoggingGateway
from app.contract.meeting_service import IMeetingService
from app.contract.messaging_service import IMessagingService

FLAGS_KEY = "m.agent_flags"

KNOWN_USERS_LIST_KEY = "known_users_list"

SYNC_KEY = "matrix_client_sync_next_batch"


class Callbacks:
    """Class to pass client to callback methods."""

    def __init__(
        self,
        client: AsyncClient,
        completion_gateway: ICompletionGateway,
        keyval_storage_gateway: IKeyValStorageGateway,
        knowledge_retrieval_gateway: IKnowledgeRetrievalGateway,
        logging_gateway: ILoggingGateway,
        meeting_service: IMeetingService,
        messaging_service: IMessagingService,
    ) -> None:
        """Store AsyncClient"""
        self._client = client
        self._completion_gateway = completion_gateway
        self._keyval_storage_gateway = keyval_storage_gateway
        self._knoweldge_retrieval_gateway = knowledge_retrieval_gateway
        self._logging_gateway = logging_gateway
        self._meeting_service = meeting_service
        self._messaging_service = messaging_service

    # Events
    async def invite_alias_event(self, event: InviteAliasEvent) -> None:
        """Handle InviteAliasEvents."""
        self._logging_gateway.info(f"InviteAliasEvent: {event.sender}")

    async def invite_member_event(
        self, room: MatrixInvitedRoom, event: InviteMemberEvent
    ) -> None:
        """Handle InviteMemberEvents."""
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
            known_users = {}
            if not self._keyval_storage_gateway.has_key(KNOWN_USERS_LIST_KEY):
                # Create a new known user list.
                known_users[event.sender] = {
                    "displayname": resp.displayname,
                    "dm_id": room.room_id,
                }
            else:
                # Load existing known user list.
                known_users = dict(
                    pickle.loads(
                        self._keyval_storage_gateway.get(KNOWN_USERS_LIST_KEY, False)
                    )
                )
                # Add user to existing known user list.
                # Overwrite existing data just in case we are not working with
                # a clean data store.
                known_users[event.sender] = {
                    "displayname": resp.displayname,
                    "dm_id": room.room_id,
                }
            self._keyval_storage_gateway.put(
                KNOWN_USERS_LIST_KEY, pickle.dumps(known_users)
            )

    async def invite_name_event(
        self, _room: MatrixInvitedRoom, event: InviteNameEvent
    ) -> None:
        """Handle InviteNameEvents."""
        self._logging_gateway.info(f"InviteNameEvent: {event.sender}")

    async def room_create_event(
        self, _room: MatrixRoom, event: RoomCreateEvent
    ) -> None:
        """Handle RoomCreateEvents."""

    async def room_message_text(
        self, room: MatrixRoom, message: RoomMessageText
    ) -> None:
        """Handle RoomMessageText."""
        # Only process messages from direct chats for now.
        is_direct = await self.is_direct_message(room.room_id)
        if message.sender == self._client.user_id or not is_direct:
            return

        # Allow the messaging service to process the message.
        await self._messaging_service.handle_text_message(
            room.room_id,
            message.event_id,
            message.sender,
            message.body,
            KNOWN_USERS_LIST_KEY,
        )

    async def tag_event(self, event: TagEvent) -> None:
        """Handle TagEvents."""
        self._logging_gateway.info(f"TagEvent: {event.sender}")

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

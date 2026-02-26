"""Provides an implementation of IIPCExtension to manage rooms."""

__all__ = ["RoomManagementIPCExtension"]

import pickle

from mugen.core import di
from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.ipc import IPCCommandRequest, IPCHandlerResult


def _matrix_client_provider():
    return di.container.matrix_client


def _keyval_storage_gateway_provider():
    return di.container.keyval_storage_gateway


def _logging_gateway_provider():
    return di.container.logging_gateway


class RoomManagementIPCExtension(IIPCExtension):
    """An implementation of IIPCExtension to manage rooms."""

    def __init__(
        self,
        matrix_client: IMatrixClient | None = None,
        keyval_storage_gateway: IKeyValStorageGateway | None = None,
        logging_gateway: ILoggingGateway | None = None,
    ) -> None:
        self._client = (
            matrix_client
            if matrix_client is not None
            else _matrix_client_provider()
        )
        self._keyval_storage_gateway = (
            keyval_storage_gateway
            if keyval_storage_gateway is not None
            else _keyval_storage_gateway_provider()
        )
        self._logging_gateway = (
            logging_gateway
            if logging_gateway is not None
            else _logging_gateway_provider()
        )

    @property
    def ipc_commands(self) -> list[str]:
        return [
            "matrix_leave_all_rooms",
            "matrix_leave_empty_rooms",
            "matrix_list_rooms",
        ]

    @property
    def platforms(self) -> list[str]:
        """Get the platform that the extension is targeting."""
        return ["matrix"]

    async def process_ipc_command(
        self,
        request: IPCCommandRequest,
    ) -> IPCHandlerResult:
        handler_name = type(self).__name__
        self._logging_gateway.debug(
            "RoomManagementIPCExtension: Executing command:"
            f" {request.command}"
        )
        match request.command:
            case "matrix_leave_all_rooms":
                await self._leave_all_rooms()
                return IPCHandlerResult(
                    handler=handler_name,
                    response={"response": "OK"},
                )
            case "matrix_leave_empty_rooms":
                await self._leave_empty_rooms()
                return IPCHandlerResult(
                    handler=handler_name,
                    response={"response": "OK"},
                )
            case "matrix_list_rooms":
                return IPCHandlerResult(
                    handler=handler_name,
                    response={"response": {"rooms": await self._list_rooms()}},
                )
            case _:
                return IPCHandlerResult(
                    handler=handler_name,
                    ok=False,
                    code="not_found",
                    error="Unsupported IPC command.",
                )

    async def _leave_all_rooms(self) -> None:
        """Leave all rooms joined by the assistant."""
        # Tasks:
        ## 1. Kick users.
        ## 2. Leave room.
        ###
        for room_id in await self._joined_room_ids():
            members = await self._client.joined_members(room_id)
            to_kick = self._collect_member_ids(members)
            ## 1. Kick users from room.
            for user_id in to_kick:
                self._logging_gateway.debug(
                    f"Kicking user {user_id} from room {room_id}."
                )
                await self._client.room_kick(room_id, user_id)
            ## 2. Leave room.
            await self._util_leave_room(room_id)

    async def _leave_empty_rooms(self) -> None:
        # Tasks:
        ## 1. Find empty room.
        ## 2. Leave room.
        ###
        for room_id in await self._joined_room_ids():
            members = await self._client.joined_members(room_id)
            members_list = getattr(members, "members", [])
            if not isinstance(members_list, list):
                continue
            if len(members_list) != 1:
                continue
            first_member_user_id = getattr(members_list[0], "user_id", None)
            ## 1. Find empty room.
            if self._client.user_id == first_member_user_id:
                self._logging_gateway.debug(f"Found empty room: {room_id}")
                ## 2. Leave room.
                await self._util_leave_room(room_id)

    async def _list_rooms(self) -> list[dict]:
        # Tasks:
        ## 1. List all rooms.
        ## 2. Determine if room is encrypted.
        ## 3. Determine if room is direct chat.
        ## 4. Get room name if available.
        ## 5. List all members of the rooms.
        ## 6. List all chat threads.
        ###
        response = []
        ## 1. List all rooms.
        for room_id in await self._joined_room_ids():
            response.append(
                {
                    "room_id": room_id,
                    "members": [],
                    "chat_threads": [],
                }
            )
            room_state = await self._client.room_get_state(room_id)
            events = self._state_events(room_state)
            ## 2. Determine if room is encrypted.
            room_encrypted_content = self._state_event_content(
                events,
                "m.room.encryption",
            )
            if room_encrypted_content is not None:
                encryption_algorithm = room_encrypted_content.get("algorithm")
                if isinstance(encryption_algorithm, str):
                    response[-1]["encrypted"] = encryption_algorithm
            ## 3. Determine if room is direct chat.
            room_direct_content = self._state_event_content(
                events,
                "m.agent_flags",
            )
            if room_direct_content is not None:
                response[-1]["direct"] = bool(room_direct_content.get("m.direct"))
            ## 4. Get room name if available.
            room_name_content = self._state_event_content(events, "m.room.name")
            if room_name_content is not None:
                room_name = room_name_content.get("name")
                if isinstance(room_name, str):
                    response[-1]["room_name"] = room_name
            ## 5. List all members of the room.
            members = await self._client.joined_members(room_id)
            for user_id in self._collect_member_ids(members):
                response[-1]["members"].append(user_id)
            ## 6. List all chat threads.
            response[-1]["chat_threads"] = self._load_chat_thread_keys(room_id)
        return response

    async def _util_leave_room(self, room_id: str) -> None:
        # Tasks:
        ## 1. Leave room.
        ## 2. Delete chat threads.
        ## 3. Delete chat threads list.
        ###
        ## 1. Leave room.
        self._logging_gateway.debug(f"Leaving room {room_id}.")
        await self._client.room_leave(room_id)
        chat_threads_list_key = f"chat_threads_list:{room_id}"
        if self._keyval_storage_gateway.has_key(chat_threads_list_key):
            ## 2. Delete chat threads.
            for chat_thread_key in self._load_chat_thread_keys(room_id):
                self._logging_gateway.debug(f"Deleting chat thread: {chat_thread_key}.")
                self._keyval_storage_gateway.remove(chat_thread_key)
            ## 3. Delete chat threads list.
            self._logging_gateway.debug(
                f"Deleting chat threads list: {chat_threads_list_key}."
            )
            self._keyval_storage_gateway.remove(chat_threads_list_key)

    async def _joined_room_ids(self) -> list[str]:
        rooms = await self._client.joined_rooms()
        room_ids = getattr(rooms, "rooms", None)
        if not isinstance(room_ids, list):
            return []
        return [item for item in room_ids if isinstance(item, str) and item != ""]

    def _collect_member_ids(self, joined_members_response) -> list[str]:
        collected: list[str] = []
        members = getattr(joined_members_response, "members", [])
        if not isinstance(members, list):
            return collected
        assistant_user_id = getattr(self._client, "user_id", None)
        for user in members:
            user_id = getattr(user, "user_id", None)
            if not isinstance(user_id, str) or user_id == "":
                continue
            if user_id == assistant_user_id:
                continue
            collected.append(user_id)
        return collected

    @staticmethod
    def _state_events(room_state_response) -> list:
        events = getattr(room_state_response, "events", None)
        if not isinstance(events, list):
            return []
        return events

    @staticmethod
    def _state_event_content(events: list, event_type: str) -> dict | None:
        for event in events:
            if isinstance(event, dict):
                candidate_type = event.get("type")
                content = event.get("content")
            else:
                candidate_type = getattr(event, "type", None)
                content = getattr(event, "content", None)
            if candidate_type != event_type:
                continue
            if isinstance(content, dict):
                return content
            return None
        return None

    def _load_chat_thread_keys(self, room_id: str) -> list[str]:
        chat_threads_list_key = f"chat_threads_list:{room_id}"
        if not self._keyval_storage_gateway.has_key(chat_threads_list_key):
            return []
        raw_payload = self._keyval_storage_gateway.get(chat_threads_list_key, False)
        if raw_payload in [None, ""]:
            return []
        if isinstance(raw_payload, str):
            raw_payload = raw_payload.encode("utf-8")
        if not isinstance(raw_payload, bytes):
            return []
        try:
            chat_threads_list = pickle.loads(raw_payload)
        except (
            pickle.PickleError,
            TypeError,
            ValueError,
            EOFError,
            AttributeError,
            ImportError,
        ):
            self._logging_gateway.warning(
                "RoomManagementIPCExtension: Failed to decode chat thread list."
                f" room_id={room_id}"
            )
            return []
        if not isinstance(chat_threads_list, dict):
            return []
        threads = chat_threads_list.get("threads")
        if not isinstance(threads, list):
            return []
        return [item for item in threads if isinstance(item, str) and item != ""]

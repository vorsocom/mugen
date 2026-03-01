"""Provides an implementation of IIPCExtension to manage rooms."""

__all__ = ["RoomManagementIPCExtension"]

from mugen.core import di
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.ipc import IPCCommandRequest, IPCHandlerResult
from mugen.core.plugin.matrix.contract import IMatrixRoomAdminClient


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
        matrix_client: IMatrixRoomAdminClient | None = None,
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
            members = await self._client.joined_member_ids(room_id)
            to_kick = [
                user_id
                for user_id in members
                if user_id != self._client.current_user_id
            ]
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
            members = await self._client.joined_member_ids(room_id)
            if len(members) != 1:
                continue
            first_member_user_id = members[0]
            ## 1. Find empty room.
            if self._client.current_user_id == first_member_user_id:
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
        direct_room_ids = await self._direct_room_ids()
        ## 1. List all rooms.
        for room_id in await self._joined_room_ids():
            response.append(
                {
                    "room_id": room_id,
                    "members": [],
                    "chat_threads": [],
                }
            )
            events = await self._client.room_state_events(room_id)
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
            response[-1]["direct"] = room_id in direct_room_ids
            ## 4. Get room name if available.
            room_name_content = self._state_event_content(events, "m.room.name")
            if room_name_content is not None:
                room_name = room_name_content.get("name")
                if isinstance(room_name, str):
                    response[-1]["room_name"] = room_name
            ## 5. List all members of the room.
            for user_id in await self._client.joined_member_ids(room_id):
                if user_id == self._client.current_user_id:
                    continue
                response[-1]["members"].append(user_id)
            ## 6. List all chat threads.
            response[-1]["chat_threads"] = await self._load_chat_thread_keys(room_id)
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
        if await self._keyval_storage_gateway.exists(chat_threads_list_key):
            ## 2. Delete chat threads.
            for chat_thread_key in await self._load_chat_thread_keys(room_id):
                self._logging_gateway.debug(f"Deleting chat thread: {chat_thread_key}.")
                await self._keyval_storage_gateway.delete(chat_thread_key)
            ## 3. Delete chat threads list.
            self._logging_gateway.debug(
                f"Deleting chat threads list: {chat_threads_list_key}."
            )
            await self._keyval_storage_gateway.delete(chat_threads_list_key)

    async def _joined_room_ids(self) -> list[str]:
        return await self._client.joined_room_ids()

    async def _direct_room_ids(self) -> set[str]:
        try:
            return await self._client.direct_room_ids()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "RoomManagementIPCExtension: direct-room lookup failed "
                f"error={type(exc).__name__}: {exc}"
            )
            return set()

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

    async def _load_chat_thread_keys(self, room_id: str) -> list[str]:
        chat_threads_list_key = f"chat_threads_list:{room_id}"
        if not await self._keyval_storage_gateway.exists(chat_threads_list_key):
            return []
        payload = await self._keyval_storage_gateway.get_json(chat_threads_list_key)
        if payload in [None, ""]:
            return []
        if not isinstance(payload, dict):
            self._logging_gateway.warning(
                "RoomManagementIPCExtension: Invalid chat thread list payload."
                f" room_id={room_id}"
            )
            return []
        threads = payload.get("threads")
        if not isinstance(threads, list):
            return []
        return [item for item in threads if isinstance(item, str) and item != ""]

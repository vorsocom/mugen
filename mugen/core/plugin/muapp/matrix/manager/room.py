"""Provides an implementation of IIPCExtension to manage rooms."""

__all__ = ["RoomManagementIPCExtension"]

import pickle

from dependency_injector.wiring import inject, Provide

from mugen.core.contract.client.matrix import IMatrixClient
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.di import DIContainer


class RoomManagementIPCExtension(IIPCExtension):
    """An implementation of IIPCExtension to manage rooms."""

    @inject
    def __init__(
        self,
        matrix_client: IMatrixClient = Provide[DIContainer.matrix_client],
        keyval_storage_gateway: IKeyValStorageGateway = Provide[
            DIContainer.keyval_storage_gateway
        ],
        logging_gateway: ILoggingGateway = Provide[DIContainer.logging_gateway],
    ) -> None:
        self._client = matrix_client
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway

    @property
    def ipc_commands(self) -> list[str]:
        return [
            "matrix_leave_all_rooms",
            "matrix_leave_empty_rooms",
            "matrix_list_rooms",
        ]

    @property
    def platforms(self) -> list[str]:
        return ["matrix"]

    async def process_ipc_command(self, payload: dict) -> None:
        self._logging_gateway.debug(
            f"RoomManagementIPCExtension: Executing command: {payload['command']}"
        )
        match payload["command"]:
            case "matrix_leave_all_rooms":
                await self._leave_all_rooms(payload)
                return
            case "matrix_leave_empty_rooms":
                await self._leave_empty_rooms(payload)
                return
            case "matrix_list_rooms":
                await self._list_rooms(payload)
                return
            case _:
                ...

    async def _leave_all_rooms(self, payload: dict) -> None:
        """Leave all rooms joined by the assistant."""
        # Tasks:
        ## 1. Kick users.
        ## 2. Leave room.
        ###
        rooms = await self._client.joined_rooms()
        for room_id in rooms.rooms:
            members = await self._client.joined_members(room_id)
            to_kick = [
                x.user_id for x in members.members if x.user_id != self._client.user_id
            ]
            ## 1. Kick users from room.
            for user_id in to_kick:
                self._logging_gateway.debug(
                    f"Kicking user {user_id} from room {room_id}."
                )
                await self._client.room_kick(room_id, user_id)
            ## 2. Leave room.
            await self._util_leave_room(room_id)

        await payload["response_queue"].put(
            {"response": "OK"},
        )

    async def _leave_empty_rooms(self, payload: dict) -> None:
        # Tasks:
        ## 1. Find empty room.
        ## 2. Leave room.
        ###
        rooms = await self._client.joined_rooms()
        for room_id in rooms.rooms:
            members = await self._client.joined_members(room_id)
            ## 1. Find empty room.
            if (
                len(members.members) == 1
                and self._client.user_id == members.members[0].user_id
            ):
                self._logging_gateway.debug(f"Found empty room: {room_id}")
                ## 2. Leave room.
                await self._util_leave_room(room_id)

        await payload["response_queue"].put(
            {"response": "OK"},
        )

    async def _list_rooms(self, payload: dict) -> None:
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
        rooms = await self._client.joined_rooms()
        for room_id in rooms.rooms:
            response.append(
                {
                    "room_id": room_id,
                    "members": [],
                    "chat_threads": [],
                }
            )
            room_state = await self._client.room_get_state(room_id)
            ## 2. Determine if room is encrypted.
            room_encrypted_event = [
                x for x in room_state.events if x["type"] == "m.room.encryption"
            ]
            if len(room_encrypted_event) != 0:
                response[-1]["encrypted"] = room_encrypted_event[0]["content"][
                    "algorithm"
                ]
            ## 3. Determine if room is direct chat.
            room_direct_event = [
                x for x in room_state.events if x["type"] == "m.agent_flags"
            ]
            if len(room_direct_event) != 0:
                response[-1]["direct"] = room_direct_event[0]["content"]["m.direct"]
            ## 4. Get room name if available.
            room_name_event = [
                x for x in room_state.events if x["type"] == "m.room.name"
            ]
            if len(room_name_event) != 0:
                response[-1]["room_name"] = room_name_event[0]["content"]["name"]
            ## 5. List all members of the room.
            members = await self._client.joined_members(room_id)
            for user in members.members:
                if user.user_id != self._client.user_id:
                    response[-1]["members"].append(user.user_id)
            ## 6. List all chat threads.
            chat_threads_list_key = f"chat_threads_list:{room_id}"
            if self._keyval_storage_gateway.has_key(chat_threads_list_key):
                chat_threads_list = pickle.loads(
                    self._keyval_storage_gateway.get(chat_threads_list_key, False)
                )
                for chat_thread_key in chat_threads_list["threads"]:
                    response[-1]["chat_threads"].append(chat_thread_key)

        await payload["response_queue"].put(
            {
                "response": {
                    "rooms": response,
                },
            }
        )

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
            chat_threads_list = pickle.loads(
                self._keyval_storage_gateway.get(chat_threads_list_key, False)
            )
            ## 2. Delete chat threads.
            for chat_thread_key in chat_threads_list["threads"]:
                self._logging_gateway.debug(f"Deleting chat thread: {chat_thread_key}.")
                self._keyval_storage_gateway.remove(chat_thread_key)
            ## 3. Delete chat threads list.
            self._logging_gateway.debug(
                f"Deleting chat threads list: {chat_threads_list_key}."
            )
            self._keyval_storage_gateway.remove(chat_threads_list_key)

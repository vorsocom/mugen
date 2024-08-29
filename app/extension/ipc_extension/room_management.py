"""Provides an implementation of IIPCExtension to manage rooms."""

__all__ = ["RoomManagementIPCExtension"]

import pickle

from dependency_injector.wiring import inject, Provide
from nio import AsyncClient

from app.core.contract.ipc_extension import IIPCExtension
from app.core.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.core.contract.logging_gateway import ILoggingGateway
from app.core.contract.user_service import IUserService
from app.core.di import DIContainer


class RoomManagementIPCExtension(IIPCExtension):
    """An implementation of IIPCExtension to manage rooms."""

    @inject
    def __init__(
        self,
        client: AsyncClient = Provide[DIContainer.client],
        keyval_storage_gateway: IKeyValStorageGateway = Provide[
            DIContainer.keyval_storage_gateway
        ],
        logging_gateway: ILoggingGateway = Provide[DIContainer.logging_gateway],
        user_service: IUserService = Provide[DIContainer.user_service],
    ) -> None:
        self._client = client
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._user_service = user_service

    @property
    def ipc_commands(self) -> list[str]:
        return ["leave_all_rooms"]

    async def process_ipc_command(self, payload: dict) -> None:
        self._logging_gateway.warning(
            f"RoomManagementIPCExtension: Executing command: {payload['command']}"
        )
        match payload["command"]:
            case "leave_all_rooms":
                await self._leave_all_rooms()
                return
            case _:
                ...

    async def _leave_all_rooms(self) -> None:
        """Leave all rooms joined by the assistant."""
        # Tasks.
        ## 1. Kick users.
        ## 2. Leave room.
        ## 3. Delete chat threads.
        ## 4. Delete chat threads list.
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
            self._logging_gateway.debug(f"Leaving room {room_id}.")
            await self._client.room_leave(room_id)
            chat_threads_list_key = f"chat_threads_list:{room_id}"
            if self._keyval_storage_gateway.has_key(chat_threads_list_key):
                chat_threads_list = pickle.loads(
                    self._keyval_storage_gateway.get(chat_threads_list_key, False)
                )
                ## 3. Delete chat threads.
                for chat_thread_key in chat_threads_list["threads"]:
                    self._logging_gateway.debug(
                        f"Deleting chat thread: {chat_thread_key}."
                    )
                    self._keyval_storage_gateway.remove(chat_thread_key)
                ## 4. Delete chat threads list.
                self._logging_gateway.debug(
                    f"Deleting chat threads list: {chat_threads_list_key}."
                )
                self._keyval_storage_gateway.remove(chat_threads_list_key)

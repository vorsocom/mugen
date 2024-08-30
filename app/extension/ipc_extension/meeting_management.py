"""Provides an implementation of IIPCExtension for managing meetings."""

__all__ = ["MeetingManagementIPCExtension"]

from datetime import datetime
import pickle

from dependency_injector.wiring import inject, Provide
from nio import AsyncClient

from app.core.contract.ipc_extension import IIPCExtension
from app.core.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.core.contract.logging_gateway import ILoggingGateway
from app.core.contract.user_service import IUserService
from app.core.di import DIContainer

from app.extension.domain.entity.meeting import CreateMeetingDTO, Meeting
from app.extension.domain.use_case.cancel_scheduled_meeting import (
    CancelScheduledMeetingInteractor,
    CancelScheduledMeetingRequest,
)


class MeetingManagementIPCExtension(IIPCExtension):
    """An implementation of IIPCExtension for managing meetings."""

    _scheduled_meeting_key = "scheduled_meeting:{0}"

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

        self._meeting_canceller = CancelScheduledMeetingInteractor(
            self._client,
            self._keyval_storage_gateway,
            self._scheduled_meeting_key,
            self._user_service,
        )

    @property
    def ipc_commands(self) -> list[str]:
        return [
            "delete_expired_meetings",
        ]

    async def process_ipc_command(self, payload: dict) -> None:
        self._logging_gateway.debug(
            "MeetingManagementIPCExtension: Executing command:"
            f" {payload['data']['command']}"
        )
        match payload["data"]["command"]:
            case "delete_expired_meetings":
                await self._delete_expired_meetings(payload)
                return
            case _:
                ...

    async def _delete_expired_meetings(self, payload: dict) -> None:
        """Delete all expired meetings."""
        meetings = [
            pickle.loads(self._keyval_storage_gateway.get(x, False))
            for x in self._keyval_storage_gateway.keys()
            if "scheduled_meeting:" in x
        ]
        for item in meetings:
            meeting = Meeting(
                init=CreateMeetingDTO(
                    item["type"],
                    item["topic"],
                    item["date"],
                    item["time"],
                    item["attendees"],
                    item["scheduler"],
                ),
                expires_after=item["expires_after"],
                room_id=item["room_id"],
            )

            meeting_time = datetime.strptime(
                f"{meeting.init.date} {meeting.init.time}", "%Y-%m-%d %H:%M:%S"
            )
            if datetime.now() > meeting_time:
                elapsed_time = (datetime.now() - meeting_time).total_seconds()
                self._logging_gateway.debug(f"Elapsed: {elapsed_time}")
                expiry_time = meeting.expires_after
                self._logging_gateway.debug(f"Expiry time: {expiry_time}")
                if elapsed_time > expiry_time:
                    self._logging_gateway.debug("Meeting to be deleted.")
                    self._logging_gateway.warning(
                        f"Deleting meeting: {meeting.init.topic} ({meeting.room_id})."
                    )
                    cancel_request = CancelScheduledMeetingRequest(
                        meeting,
                        meeting.init.scheduler,
                    )
                    await self._meeting_canceller.handle(cancel_request)

        await payload["response_queue"].put(
            {"response": "OK"},
        )

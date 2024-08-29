"""Provides an interactor to schedule a meeting."""

# pylint: disable=too-few-public-methods

__all__ = ["ScheduleMeetingInteractor"]

import asyncio
import pickle
from types import SimpleNamespace

from nio import AsyncClient, RoomCreateResponse

from app.core.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.core.contract.request_handler import IRequestHandler
from app.core.contract.user_service import IUserService

from app.extension.domain.entity.meeting import Meeting
from app.extension.domain.use_case.schedule_meeting.request import (
    ScheduleMeetingRequest,
)
from app.extension.domain.use_case.schedule_meeting.response import (
    ScheduleMeetingResponse,
)

INPERSON_MEETING_INVITE = (
    'You\'ve been invited to an in-person meeting "{0}" scheduled for the {1}'
    " on {2} at {3}. The meeting is being tracked using room {4}."
)

INPERSON_MEETING_ROOM_NOTE = (
    "This meeting room was created by {0} to track an in-person meeting scheduled for"
    " the {1} to discuss {2} on {3} at {4}. You may use this room to share relevant"
    " meeting documents. Note that this room will be deleted {5} hours after the"
    " scheduled meeting time."
)

VIRTUAL_MEETING_INVITE = (
    'You\'ve been invited to a virtual meeting "{0}" to be held in room {1}'
    " on {2} at {3}"
)

VIRTUAL_MEETING_ROOM_NOTE = (
    "This meeting room was created by {0} to host a virtual meeting to discuss {1} on"
    " {2} at {3}. You may use this room to share relevant meeting documents. Note that"
    " this room will be deleted {4} hours after the scheduled meeting time."
)


class ScheduleMeetingInteractor(
    IRequestHandler["ScheduleMeetingRequest", "ScheduleMeetingResponse"]
):
    """An interactor to handle a request to schedule a meeting."""

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        client: AsyncClient,
        config: SimpleNamespace,
        keyval_storage_gateway: IKeyValStorageGateway,
        scheduled_meeting_key: str,
        user_service: IUserService,
    ) -> None:
        self._client = client
        self._config = config
        self._keyval_storage_gateway = keyval_storage_gateway
        self._scheduled_meeting_key = scheduled_meeting_key
        self._user_service = user_service

    async def handle(self, request: ScheduleMeetingRequest) -> ScheduleMeetingResponse:
        # Create a failed response to use in case of failures/errors.
        failed_response = ScheduleMeetingResponse(False)

        # Create a list to hold reponse messages.
        messages = []

        # Create a new Meeting object.
        meeting = Meeting(init=request.init_data)

        # If the meeting is an in-person meeting:
        if not meeting.is_virtual():
            # The request should provide a location.
            # If the request does not provide a location:
            if request.location is None:
                # Set response message.
                messages.append("InPersonMeetingNoLocation")
                failed_response.messages = messages
                # Return failure.
                return failed_response

            # else:
            # Set the meeting location.
            meeting.location = request.location

        # else:
        # Set the expires_after attribute of the meeting.
        # If this value is not supplied the meeting room will not be deleted from the
        # platform automatically.
        meeting.expires_after = request.expires_after

        # Attempt to create the meeting room.
        room_id = await self._meeting_create_room(meeting)

        # If the attempt to create the meeting room has failed.
        if room_id is None:
            # Set response message.
            messages.append("CreateRoomFailure")
            failed_response.messages = messages
            # Return failure.
            return failed_response

        # else:
        # Add newly generated room_id to meeting
        meeting.room_id = room_id

        # Persist the scheduled meeting data.
        self._meeting_persist_data(meeting)

        # else:
        # Notify invited users.
        notified = await self._meeting_notify_invitees(meeting)

        # If the attempt to notify the attendees of the meeting has failed.
        if notified is False:
            # Set response message.
            messages.append("NotifyAttendeesFailure")
            ##failed_response.messages = messages
            # Return failure.
            ##return failed_response

        # else:
        # The meeting room was created, meeting data persisted, and attendees notified.
        # Return success.
        return ScheduleMeetingResponse(True, messages, meeting)

    async def _meeting_create_room(self, meeting: Meeting) -> str | None:
        """Create a room to host a meeting."""
        # Create room
        room_name = f"{meeting.init.type.capitalize()} Meeting: {meeting.init.topic}"

        create_room_resp = await self._client.room_create(
            name=room_name, invite=meeting.init.attendees
        )

        if not isinstance(create_room_resp, RoomCreateResponse):
            return None

        # Update room permissions to allow invitees to initiate conference calls.
        room_state = await self._client.room_get_state(create_room_resp.room_id)
        state_content = [
            x for x in room_state.events if x["type"] == "m.room.power_levels"
        ][0]
        state_content["content"]["users"][self._client.user_id] = 100
        state_content["content"]["users_default"] = 50
        await self._client.room_put_state(
            room_id=create_room_resp.room_id,
            event_type="m.room.power_levels",
            content=state_content["content"],
        )
        await self._client.room_put_state(
            room_id=create_room_resp.room_id,
            event_type="m.room.encryption",
            content={
                "algorithm": "m.megolm.v1.aes-sha2",
            },
        )

        # Leave note in meeting room explaining it's purpose.
        sync_signal = asyncio.Event()

        async def wait_for_sync():
            while create_room_resp.room_id not in self._client.rooms:
                await self._client.synced.wait()
            sync_signal.set()

        async def after_sync():
            await sync_signal.wait()
            await self._client.room_send(
                room_id=create_room_resp.room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": (
                        VIRTUAL_MEETING_ROOM_NOTE.format(
                            meeting.init.scheduler,
                            meeting.init.topic,
                            meeting.init.date,
                            meeting.init.time,
                            int(int(self._config.gloria_meeting_expiry_time) / 3600),
                        )
                        if meeting.is_virtual()
                        else INPERSON_MEETING_ROOM_NOTE.format(
                            meeting.init.scheduler,
                            meeting.location,
                            meeting.init.topic,
                            meeting.init.date,
                            meeting.init.time,
                            int(int(self._config.gloria_meeting_expiry_time) / 3600),
                        )
                    ),
                },
            )

        # We have to wait until sync happends to send the message
        # in the newly create room.
        asyncio.gather(
            asyncio.create_task(wait_for_sync()),
            asyncio.create_task(after_sync()),
        )

        # Return the room_id as the location for the meeting.
        return create_room_resp.room_id

    async def _meeting_notify_invitees(self, meeting: Meeting) -> bool:
        """Notify invitees of scheduled meeting."""
        # Inform invitees of meeting.
        known_users_list = self._user_service.get_known_users_list()

        exclude = [self._client.user_id]

        for attendee in [x for x in meeting.init.attendees if x not in exclude]:
            user_data = known_users_list[attendee]
            sent = await self._client.room_send(
                room_id=user_data["dm_id"],
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": (
                        VIRTUAL_MEETING_INVITE.format(
                            meeting.init.topic,
                            meeting.room_id,
                            meeting.init.date,
                            meeting.init.time,
                        )
                        if meeting.is_virtual()
                        else INPERSON_MEETING_INVITE.format(
                            meeting.init.topic,
                            meeting.location,
                            meeting.init.date,
                            meeting.init.time,
                            meeting.room_id,
                        )
                    ),
                },
            )

            if not sent:
                return False

        return True

    def _meeting_persist_data(self, meeting: Meeting) -> None:
        """Persist meeting data to key-value storage."""
        self._keyval_storage_gateway.put(
            self._scheduled_meeting_key.format(meeting.room_id),
            (
                pickle.dumps(
                    {
                        "type": meeting.init.type,
                        "topic": meeting.init.topic,
                        "date": meeting.init.date,
                        "time": meeting.init.time,
                        "attendees": meeting.init.attendees,
                        "scheduler": meeting.init.scheduler,
                        "room_id": meeting.room_id,
                        "expires_after": meeting.expires_after,
                        "location": meeting.location,
                    }
                )
            ),
        )

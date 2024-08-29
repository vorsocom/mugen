"""Provides an interactor to update a scheduled meeting."""

__all__ = ["UpdateScheduledMeetingInteractor"]

import pickle

from nio import AsyncClient, RoomPutStateResponse

from app.core.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.core.contract.user_service import IUserService
from app.core.contract.request_handler import IRequestHandler

from app.extension.domain.entity.meeting import Meeting
from app.extension.domain.use_case.update_scheduled_meeting.request import (
    UpdateScheduledMeetingRequest,
)
from app.extension.domain.use_case.update_scheduled_meeting.response import (
    UpdateScheduledMeetingResponse,
)

INPERSON_MEETING_ROOM_NOTE_UPDATE = (
    "The meeting details have been updated. See below for change(s).\n"
    "Location: {0}.\n"
    "Topic: {1}.\n"
    "Date: {2}.\n"
    "Time: {3}.\n"
)

MEETING_UPDATE = (
    'The details of the meeting "{0}" have been updated. See room {1} for more details.'
)

VIRTUAL_MEETING_ROOM_NOTE_UPDATE = (
    "The meeting details have been updated. See below for change(s).\n"
    "Topic: {0}.\n"
    "Date: {1}.\n"
    "Time: {2}.\n"
)


# pylint: disable=too-few-public-methods
class UpdateScheduledMeetingInteractor(
    IRequestHandler["UpdateScheduledMeetingRequest", "UpdateScheduledMeetingResponse"]
):
    """An interactor to handle a request to update a scheduled meeting."""

    def __init__(
        self,
        client: AsyncClient,
        keyval_storage_gateway: IKeyValStorageGateway,
        scheduled_meeting_key: str,
        user_service: IUserService,
    ) -> None:
        self._client = client
        self._keyval_storage_gateway = keyval_storage_gateway
        self._scheduled_meeting_key = scheduled_meeting_key
        self._user_service = user_service

    async def handle(
        self, request: UpdateScheduledMeetingRequest
    ) -> UpdateScheduledMeetingResponse:
        # Create a failed response to use in case of failures/errors.
        _failed_response = UpdateScheduledMeetingResponse(False)

        # Create a list to hold reponse messages.
        messages = []

        # Create a new Meeting object.
        meeting = request.meeting

        # Persist the meeting updates.
        self._meeting_persist_data(meeting)

        # else:
        # If the meeting topic has changed, change the name of the room.
        if request.change_topic:
            name_changed = await self._meeting_update_room_name(meeting)
            if name_changed is False:
                messages.append("MeetingRoomNameChangeFailure")

        # Update note in meeting room.
        note_updated = await self._meeting_update_room_note(meeting)

        # If the attempt to update the note in the meeting room has failed.
        if note_updated is False:
            # Set response message.
            messages.append("MeetingRoomNoteUpdateFailure")

        # else:
        # Notify attendees of updates.
        notified = await self._meeting_notify_update(meeting)

        # If the attempt to notify the attendees of the updates has failed.
        if notified is False:
            # Set response message.
            messages.append("NotifyUpdateFailure")

        # else:
        # The meeting was updated.
        # Return success.
        return UpdateScheduledMeetingResponse(True, messages, meeting)

    async def _meeting_notify_update(self, meeting: Meeting) -> bool:
        """Notify attendees of updated meeting information."""
        # Inform attendees of meeting updates.
        known_users_list = self._user_service.get_known_users_list()

        exclude = [self._client.user_id]

        for attendee in [x for x in meeting.init.attendees if x not in exclude]:
            user_data = known_users_list[attendee]
            sent = await self._client.room_send(
                room_id=user_data["dm_id"],
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": MEETING_UPDATE.format(meeting.init.topic, meeting.room_id),
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

    async def _meeting_update_room_name(self, meeting: Meeting) -> bool:
        """Change the name of a room create for a scheduled meeting."""
        # Create room
        room_name = f"{meeting.init.type.capitalize()} Meeting: {meeting.init.topic}"

        response = await self._client.room_put_state(
            room_id=meeting.room_id,
            event_type="m.room.name",
            content={"name": room_name},
        )

        if not isinstance(response, RoomPutStateResponse):
            return False

        return True

    async def _meeting_update_room_note(self, meeting: Meeting) -> bool:
        """Leave a note in the meeting room on the updated meeting information."""
        # Leave note in meeting room with updated information.
        return await self._client.room_send(
            room_id=meeting.room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": (
                    VIRTUAL_MEETING_ROOM_NOTE_UPDATE.format(
                        meeting.init.topic,
                        meeting.init.time,
                        meeting.init.date,
                    )
                    if meeting.init.type == "virtual"
                    else INPERSON_MEETING_ROOM_NOTE_UPDATE.format(
                        meeting.location,
                        meeting.init.topic,
                        meeting.init.time,
                        meeting.init.date,
                    )
                ),
            },
        )

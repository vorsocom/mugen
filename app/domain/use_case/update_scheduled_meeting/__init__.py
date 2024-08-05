"""Provides an interactor to update a scheduled meeting."""

# pylint: disable=too-few-public-methods

__all__ = ["UpdateScheduledMeetingInteractor"]

from app.contract.platform_gateway import IPlatformGateway
from app.contract.request_handler import IRequestHandler

from app.domain.entity.meeting import Meeting

from app.domain.use_case.update_scheduled_meeting.request import (
    UpdateScheduledMeetingRequest,
)
from app.domain.use_case.update_scheduled_meeting.response import (
    UpdateScheduledMeetingResponse,
)


class UpdateScheduledMeetingInteractor(
    IRequestHandler["UpdateScheduledMeetingRequest", "UpdateScheduledMeetingResponse"]
):
    """An interactor to handle a request to update a scheduled meeting."""

    def __init__(self, platform_gateway: IPlatformGateway) -> None:
        self._platform_gateway = platform_gateway

    async def handle(
        self, request: UpdateScheduledMeetingRequest
    ) -> UpdateScheduledMeetingResponse:
        # Create a failed response to use in case of failures/errors.
        failed_response = UpdateScheduledMeetingResponse(False)

        # Create a list to hold reponse messages.
        messages = []

        # Create a new Meeting object.
        meeting = request.meeting

        # Attempt to persist the meeting updates.
        persisted = self._platform_gateway.meeting_persist_data(meeting)

        # If the attempt to persist the updates has failed.
        if persisted is False:
            # Set the response message.
            messages.append("PersistMeetingUpdatesDataFailure")
            failed_response.messages = messages
            # Return failure.
            return failed_response

        # else:
        # If the meeting topic has changed, change the name of the room.
        if request.change_topic:
            name_changed = await self._platform_gateway.meeting_update_room_name(
                meeting
            )
            if name_changed is False:
                messages.append("MeetingRoomNameChangeFailure")

        # Update note in meeting room.
        note_updated = await self._platform_gateway.meeting_update_room_note(meeting)

        # If the attempt to update the note in the meeting room has failed.
        if note_updated is False:
            # Set response message.
            messages.append("MeetingRoomNoteUpdateFailure")

        # else:
        # Notify attendees of updates.
        notified = await self._platform_gateway.meeting_notify_update(meeting)

        # If the attempt to notify the attendees of the updates has failed.
        if notified is False:
            # Set response message.
            messages.append("NotifyUpdateFailure")

        # else:
        # The meeting was updated.
        # Return success.
        return UpdateScheduledMeetingResponse(True, messages, meeting)

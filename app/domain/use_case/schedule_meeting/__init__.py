"""Provides an interactor to schedule a meeting."""

# pylint: disable=too-few-public-methods

__all__ = ["ScheduleMeetingInteractor"]

from app.contract.platform_gateway import IPlatformGateway
from app.contract.request_handler import IRequestHandler

from app.domain.entity.meeting import Meeting

from app.domain.use_case.schedule_meeting.request import ScheduleMeetingRequest
from app.domain.use_case.schedule_meeting.response import ScheduleMeetingResponse


class ScheduleMeetingInteractor(
    IRequestHandler["ScheduleMeetingRequest", "ScheduleMeetingResponse"]
):
    """An interactor to handle a request to schedule a meeting."""

    def __init__(self, platform_gateway: IPlatformGateway) -> None:
        self._platform_gateway = platform_gateway

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
        room_id = await self._platform_gateway.meeting_create_room(meeting)

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

        # Attempt to persist the scheduled meeting data.
        persisted = self._platform_gateway.meeting_persist_data(meeting)

        # If the attempt to persist the scheduled meeting data has failed.
        if persisted is False:
            # Set the response message.
            await self._platform_gateway.meeting_rollback(meeting)
            messages.append("PersistMeetingDataFailure")
            failed_response.messages = messages
            # Return failure.
            return failed_response

        # else:
        # Notify invited users.
        notified = await self._platform_gateway.meeting_notify_invitees(meeting)

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

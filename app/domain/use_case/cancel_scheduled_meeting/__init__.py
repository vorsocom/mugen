"""Provides an interactor to cancel a scheduled meeting."""

# pylint: disable=too-few-public-methods

__all__ = ["CancelScheduledMeetingInteractor"]

from app.contract.platform_gateway import IPlatformGateway
from app.contract.request_handler import IRequestHandler

from app.domain.entity.meeting import Meeting

from app.domain.use_case.cancel_scheduled_meeting.request import (
    CancelScheduledMeetingRequest,
)
from app.domain.use_case.cancel_scheduled_meeting.response import (
    CancelScheduledMeetingResponse,
)


class CancelScheduledMeetingInteractor(
    IRequestHandler["CancelScheduledMeetingRequest", "CancelScheduledMeetingResponse"]
):
    """An interactor to handle a request to cancel a scheduled meeting."""

    def __init__(self, platform_gateway: IPlatformGateway) -> None:
        self._platform_gateway = platform_gateway

    async def handle(
        self, request: CancelScheduledMeetingRequest
    ) -> CancelScheduledMeetingResponse:
        # Create a failed response to use in case of failures/errors.
        failed_response = CancelScheduledMeetingResponse(False)

        # Create a list to hold reponse messages.
        messages = []

        # Remove the meeting from persistent storage.
        removed = await self._platform_gateway.meeting_remove(
            request.meeting, request.initiator
        )

        # If the attempt to remove the meeting has failed.
        if removed is False:
            # Set the response message.
            messages.append("MeetingRemoveFailure")
            failed_response.messages = messages
            # Return failure.
            return failed_response

        # else:
        # Notify attendees of cancellation.
        notified = await self._platform_gateway.meeting_notify_cancel(request.meeting)

        # If the attempt to notify the attendees of the cancellation has failed.
        if notified is False:
            # Set response message.
            messages.append("NotifyCancelFailure")

        # else:
        # The meeting was cancelled.
        # Return success.
        return CancelScheduledMeetingResponse(True, messages)

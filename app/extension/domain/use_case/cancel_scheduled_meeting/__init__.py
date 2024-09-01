"""Provides an interactor to cancel a scheduled meeting."""

# pylint: disable=too-few-public-methods

__all__ = ["CancelScheduledMeetingInteractor"]

import pickle

from nio import AsyncClient

from app.core.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.core.contract.user_service import IUserService
from app.core.contract.request_handler import IRequestHandler

from app.extension.domain.entity.meeting import Meeting
from app.extension.domain.use_case.cancel_scheduled_meeting.request import (
    CancelScheduledMeetingRequest,
)
from app.extension.domain.use_case.cancel_scheduled_meeting.response import (
    CancelScheduledMeetingResponse,
)

MEETING_CANCEL = (
    'The meeting "{0}", scheduled for room {1} on {2} at {3} has been cancelled, and'
    " the room removed."
)


class CancelScheduledMeetingInteractor(
    IRequestHandler["CancelScheduledMeetingRequest", "CancelScheduledMeetingResponse"]
):
    """An interactor to handle a request to cancel a scheduled meeting."""

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
        self, request: CancelScheduledMeetingRequest
    ) -> CancelScheduledMeetingResponse:
        # Create a failed response to use in case of failures/errors.
        failed_response = CancelScheduledMeetingResponse(False)

        # Create a list to hold reponse messages.
        messages = []

        # Remove the meeting from persistent storage.
        removed = await self._meeting_remove(request.meeting, request.initiator)

        # If the attempt to remove the meeting has failed.
        if removed is False:
            # Set the response message.
            messages.append("MeetingRemoveFailure")
            failed_response.messages = messages
            # Return failure.
            return failed_response

        # else:
        # Notify attendees of cancellation.
        notified = await self._meeting_notify_cancel(request.meeting)

        # If the attempt to notify the attendees of the cancellation has failed.
        if notified is False:
            # Set response message.
            messages.append("NotifyCancelFailure")

        # else:
        # The meeting was cancelled.
        # Return success.
        return CancelScheduledMeetingResponse(True, messages)

    async def _meeting_notify_cancel(self, meeting: Meeting) -> bool:
        """Notify attendees of cancelled meeting."""
        # Inform attendees of meeting cancellation.
        known_users_list = self._user_service.get_known_users_list()

        exclude = [self._client.user_id]

        for attendee in [x for x in meeting.init.attendees if x not in exclude]:
            user_data = known_users_list[attendee]
            sent = await self._client.room_send(
                room_id=user_data["dm_id"],
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": MEETING_CANCEL.format(
                        meeting.init.topic,
                        meeting.room_id,
                        meeting.init.date,
                        meeting.init.time,
                    ),
                },
            )

            if not sent:
                return False

        return True

    async def _meeting_remove(self, meeting: Meeting, initiator: str) -> bool:
        """Remove a scheduled meeting."""
        # Get key for persisted meeting data.
        meeting_key = self._scheduled_meeting_key.format(meeting.room_id)

        # Only the meeting scheduler can cancel a meeting.
        if initiator != meeting.init.scheduler:
            return False

        # Remove the persisted meeting data.
        self._keyval_storage_gateway.remove(meeting_key)

        # Kick all attendees from the meeting room.
        for attendee in [
            x for x in meeting.init.attendees if x != self._client.user_id
        ]:
            await self._client.room_kick(meeting.room_id, attendee)

        # The assistant can now leave the room.
        await self._client.room_leave(meeting.room_id)

        # Return success.
        return True

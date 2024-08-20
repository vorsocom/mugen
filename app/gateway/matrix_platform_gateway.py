"""Provides a platform gateway for Matrix."""

__all__ = ["MatrixPlatformGateway"]

import asyncio
import pickle
import traceback
from typing import Optional

from nio import (
    AsyncClient,
    LocalProtocolError,
    RoomCreateResponse,
    RoomPutStateResponse,
    SendRetryError,
)
from nio.exceptions import OlmUnverifiedDeviceError

from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.logging_gateway import ILoggingGateway
from app.contract.platform_gateway import IPlatformGateway

from app.domain.entity.meeting import Meeting


KNOWN_USERS_LIST_KEY = "known_users_list"

SCHEDULED_MEETING_KEY = "scheduled_meeting:{0}"

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

INPERSON_MEETING_ROOM_NOTE_UPDATE = (
    "The meeting details have been updated. See below for change(s).\n"
    "Location: {0}.\n"
    "Topic: {1}.\n"
    "Date: {2}.\n"
    "Time: {3}.\n"
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

VIRTUAL_MEETING_ROOM_NOTE_UPDATE = (
    "The meeting details have been updated. See below for change(s).\n"
    "Topic: {0}.\n"
    "Date: {1}.\n"
    "Time: {2}.\n"
)

MEETING_CANCEL = (
    'The meeting "{0}", scheduled for room {1} on {2} at {3} has been cancelled, and'
    " the room removed."
)

MEETING_UPDATE = (
    'The details of the meeting "{0}" have been updated. See room {1} for more details.'
)


class MatrixPlatformGateway(IPlatformGateway):
    """A platform gateway for Matrix."""

    def __init__(
        self,
        client: AsyncClient,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._client = client
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway

    ##########
    # MEETINGS
    ##########
    async def meeting_create_room(self, meeting: Meeting) -> Optional[str]:
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

        # Leave note in meeting room explaining it's purpose.
        sync_signal = asyncio.Event()

        async def wait_for_sync():
            while create_room_resp.room_id not in self._client.rooms:
                await self._client.synced.wait()
            sync_signal.set()

        async def after_sync():
            await sync_signal.wait()
            await self.send_text_message(
                room_id=create_room_resp.room_id,
                content={
                    "msgtype": "m.text",
                    "body": (
                        VIRTUAL_MEETING_ROOM_NOTE.format(
                            meeting.init.scheduler,
                            meeting.init.topic,
                            meeting.init.date,
                            meeting.init.time,
                            int(
                                int(
                                    self._keyval_storage_gateway.get(
                                        "gloria_meeting_expiry_time"
                                    )
                                )
                                / 3600
                            ),
                        )
                        if meeting.is_virtual()
                        else INPERSON_MEETING_ROOM_NOTE.format(
                            meeting.init.scheduler,
                            meeting.location,
                            meeting.init.topic,
                            meeting.init.date,
                            meeting.init.time,
                            int(
                                int(
                                    self._keyval_storage_gateway.get(
                                        "gloria_meeting_expiry_time"
                                    )
                                )
                                / 3600
                            ),
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

    async def meeting_notify_invitees(self, meeting: Meeting) -> bool:
        # Inform invitees of meeting.
        known_users_list = pickle.loads(
            self._keyval_storage_gateway.get(KNOWN_USERS_LIST_KEY, False)
        )
        for attendee in [
            x
            for x in meeting.init.attendees
            if x not in [self._client.user_id, meeting.init.scheduler]
        ]:
            user_data = known_users_list[attendee]
            sent = await self.send_text_message(
                room_id=user_data["dm_id"],
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

    async def meeting_notify_cancel(
        self,
        meeting: Meeting,
        assistant: bool = False,
    ) -> bool:
        # Inform attendees of meeting cancellation.
        known_users_list = pickle.loads(
            self._keyval_storage_gateway.get(KNOWN_USERS_LIST_KEY, False)
        )

        exclude = [self._client.user_id]
        if not assistant:
            exclude.append(meeting.init.scheduler)

        for attendee in [x for x in meeting.init.attendees if x not in exclude]:
            user_data = known_users_list[attendee]
            sent = await self.send_text_message(
                room_id=user_data["dm_id"],
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

    async def meeting_notify_update(self, meeting: Meeting) -> bool:
        # Inform attendees of meeting updates.
        known_users_list = pickle.loads(
            self._keyval_storage_gateway.get(KNOWN_USERS_LIST_KEY, False)
        )
        for attendee in [
            x
            for x in meeting.init.attendees
            if x not in [self._client.user_id, meeting.init.scheduler]
        ]:
            user_data = known_users_list[attendee]
            sent = await self.send_text_message(
                room_id=user_data["dm_id"],
                content={
                    "msgtype": "m.text",
                    "body": MEETING_UPDATE.format(meeting.init.topic, meeting.room_id),
                },
            )

            if not sent:
                return False

        return True

    def meeting_persist_data(self, meeting: Meeting) -> None:
        self._keyval_storage_gateway.put(
            SCHEDULED_MEETING_KEY.format(meeting.room_id),
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

    async def meeting_remove(self, meeting: Meeting, initiator: str) -> bool:
        # Get key for persisted meeting data.
        meeting_key = SCHEDULED_MEETING_KEY.format(meeting.room_id)

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
        await self._client.room_leave(self._client.user_id)

        # Return success.
        return True

    async def meeting_rollback(self, meeting: Meeting) -> bool: ...

    async def meeting_update_room_name(self, meeting: Meeting) -> bool:
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

    async def meeting_update_room_note(self, meeting: Meeting) -> bool:
        # Leave note in meeting room with updated information.
        return await self.send_text_message(
            room_id=meeting.room_id,
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

    async def send_text_message(self, room_id: str, content: str) -> bool:
        try:
            await self._client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content=content,
            )
            return True
        except (SendRetryError, LocalProtocolError, OlmUnverifiedDeviceError):
            self._logging_gateway.warning(
                "matrix_platform_gateway: Error sending text message."
            )
            traceback.print_exc()

        return False

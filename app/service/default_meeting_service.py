"""Provides an implementation of IMeetingService."""

__all__ = ["DefaultMeetingService"]

from datetime import datetime
import json
import pickle
import traceback

from nio import AsyncClient

from app.contract.completion_gateway import ICompletionGateway
from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.logging_gateway import ILoggingGateway
from app.contract.meeting_service import IMeetingService
from app.contract.platform_gateway import IPlatformGateway

from app.domain.entity.meeting import CreateMeetingDTO, Meeting
from app.domain.use_case.cancel_scheduled_meeting import (
    CancelScheduledMeetingInteractor,
    CancelScheduledMeetingRequest,
    CancelScheduledMeetingResponse,
)
from app.domain.use_case.schedule_meeting import (
    ScheduleMeetingInteractor,
    ScheduleMeetingRequest,
    ScheduleMeetingResponse,
)
from app.domain.use_case.update_scheduled_meeting import (
    UpdateScheduledMeetingInteractor,
    UpdateScheduledMeetingRequest,
    UpdateScheduledMeetingResponse,
)

INPERSON_MEETING_DATA = (
    "{0} meeting secheduled for the {1} on {2} at {3}. The room link associated with"
    " this meeting is {4}. The topic is {5} and the attendees are {6}"
)

MEETING_TRIGGERS = [
    "I'm arranging the requested meeting.",
    "I'm updating the specified meeting.",
    "I'm cancelling the specified meeting.",
]

SCHEDULED_MEETING_KEY = "scheduled_meeting:{0}"

VIRTUAL_MEETING_DATA = (
    "{0} meeting using room {1}, secheduled for {2} at {3}. The topic is {4} and the"
    " attendees are {5}"
)


class DefaultMeetingService(IMeetingService):
    """The default meeting service."""

    def __init__(
        self,
        client: AsyncClient,
        completion_gateway: ICompletionGateway,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
        platform_gateway: IPlatformGateway,
    ) -> None:
        self._client = client
        self._completion_gateway = completion_gateway
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._platform_gateway = platform_gateway
        self._meeting_canceller = CancelScheduledMeetingInteractor(
            self._platform_gateway
        )
        self._meeting_scheduler = ScheduleMeetingInteractor(self._platform_gateway)
        self._meeting_updater = UpdateScheduledMeetingInteractor(self._platform_gateway)

    async def cancel_expired_meetings(self) -> None:
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
                    cancel_request = CancelScheduledMeetingRequest(
                        meeting,
                        meeting.init.scheduler,
                    )
                    await self._meeting_canceller.handle(cancel_request)

    async def cancel_scheduled_meeting(
        self,
        user_id: str,
        chat_id: str,
        chat_thread_key: str,
    ) -> None:
        chat_thread = pickle.loads(
            self._keyval_storage_gateway.get(chat_thread_key, False)
        )
        action_parameters = await self._completion_gateway.get_completion(
            context=chat_thread["messages"]
            + [
                # Append info on tracked meetings
                {
                    "role": "system",
                    "content": self.get_scheduled_meetings_data(user_id),
                },
                {
                    "role": "user",
                    "content": (
                        "Give the room link associated with the meeting that's to"
                        " be cancelled. This link should be the only thing in your"
                        " response. The cancellation will fail if you do not"
                        " provide the room link."
                    ),
                },
            ],
            model=self._keyval_storage_gateway.get("groq_api_classification_model"),
        )
        cancel_id = (
            "" if action_parameters is None else action_parameters.content.strip()
        )

        try:
            scheduled_meeting: Meeting = pickle.loads(
                self._keyval_storage_gateway.get(
                    SCHEDULED_MEETING_KEY.format(cancel_id), False
                )
            )
        except TypeError:
            self._logging_gateway.warning("default_meeting_service: TypeError.")
            traceback.print_exc()
            return

        meeting = Meeting(
            init=CreateMeetingDTO(
                scheduled_meeting["type"],
                scheduled_meeting["topic"],
                scheduled_meeting["date"],
                scheduled_meeting["time"],
                scheduled_meeting["attendees"],
                scheduled_meeting["scheduler"],
            ),
            expires_after=scheduled_meeting["expires_after"],
            room_id=scheduled_meeting["room_id"],
        )
        cancel_request = CancelScheduledMeetingRequest(meeting, user_id)
        cancel_meeting_response: CancelScheduledMeetingResponse = (
            await self._meeting_canceller.handle(cancel_request)
        )

        if not cancel_meeting_response.success:
            # Meeting cancellation was successful.
            # Inform the user that the meeting was cancelled and the room removed.
            await self._platform_gateway.send_text_message(
                room_id=chat_id,
                content={
                    "msgtype": "m.text",
                    "body": (
                        "The meeting cancellation failed due to technical difficulties."
                        " I recommend you try again. If the problem persists, you"
                        " should report the issue to the system administrator."
                    ),
                },
            )

    def get_meeting_triggers(self) -> list[str]:
        return MEETING_TRIGGERS

    def get_scheduled_meetings_data(self, user_id: str) -> str:
        """Get data on scheduled meetings to send to assistant."""
        meetings = [
            x for x in self._keyval_storage_gateway.keys() if "scheduled_meeting:" in x
        ]
        filtered_meetings = [
            x
            for x in meetings
            if user_id
            in dict(pickle.loads(self._keyval_storage_gateway.get(x, False)))[
                "attendees"
            ]
        ]

        if len(filtered_meetings) == 0:
            return "The current user has no tracked meetings."

        resp = "The following meetings are being tracked for the current user:\n\n"

        for idx, meeting in enumerate(filtered_meetings, start=1):
            resp = resp + f"{idx}. "
            meeting_data = pickle.loads(
                self._keyval_storage_gateway.get(meeting, False)
            )

            resp = resp + (
                VIRTUAL_MEETING_DATA.format(
                    meeting_data["type"],
                    meeting_data["room_id"],
                    meeting_data["time"],
                    meeting_data["date"],
                    meeting_data["topic"],
                    ", ".join(meeting_data["attendees"]),
                )
                if meeting_data["type"] == "virtual"
                else INPERSON_MEETING_DATA.format(
                    meeting_data["type"],
                    meeting_data["location"],
                    meeting_data["date"],
                    meeting_data["time"],
                    meeting_data["room_id"],
                    meeting_data["topic"],
                    ", ".join(meeting_data["attendees"]),
                )
            )
        return resp

    async def handle_assistant_response(
        self,
        response: str,
        user_id: str,
        room_id: str,
        chat_thread_key: str,
    ) -> None:
        # If trigger detected to schedule meeting.
        if MEETING_TRIGGERS[0] in response:
            await self.schedule_meeting(user_id, room_id, chat_thread_key)

        # If trigger detected to update scheduled meeting.
        elif MEETING_TRIGGERS[1] in response:
            await self.update_scheduled_meeting(user_id, room_id, chat_thread_key)

        # If trigger detected to cancel meeting.
        elif MEETING_TRIGGERS[2] in response:
            await self.cancel_scheduled_meeting(user_id, room_id, chat_thread_key)

    async def schedule_meeting(
        self, user_id: str, chat_id: str, chat_thread_key: str
    ) -> None:
        chat_thread = pickle.loads(
            self._keyval_storage_gateway.get(chat_thread_key, False)
        )
        action_parameters = await self._completion_gateway.get_completion(
            context=chat_thread["messages"]
            + [
                {
                    "role": "user",
                    "content": (
                        "Give the meeting parameters as a JSON string. Example:"
                        ' {"type": "virtual", "topic": "example", "date": "2024-01-01",'
                        ' "time": "15:00:00", "attendees": ["@u1:example.com",'
                        ' "@u2:example.com"], "location": "loc"} Nothing else should be'
                        " in your response. The keys should be type, topic, date, time,"
                        " attendees, and location. Omit location if it's a virtual"
                        " meeting. The attendees list should just include the full"
                        " platform formatted usernames."
                    ),
                }
            ],
            model=self._keyval_storage_gateway.get("groq_api_classification_model"),
            response_format="json_object",
        )
        meeting_params = dict(
            json.loads("{}" if action_parameters is None else action_parameters.content)
        )

        # Schedule meeting using the ScheduleMeetingInteractor
        meeting_dto = CreateMeetingDTO(
            meeting_params["type"],
            meeting_params["topic"],
            meeting_params["date"],
            meeting_params["time"],
            meeting_params["attendees"],
            user_id,
        )
        meeting_request = ScheduleMeetingRequest(
            meeting_dto,
            expires_after=int(
                self._keyval_storage_gateway.get("gloria_meeting_expiry_time")
            ),
        )

        # If the meeting is in-person, we need to set the location.
        if meeting_params["type"] == "in-person":
            meeting_request.location = meeting_params["location"]

        schedule_meeting_response: ScheduleMeetingResponse = (
            await self._meeting_scheduler.handle(meeting_request)
        )

        # If scheduling the meeting failed.
        if not schedule_meeting_response.success:
            await self._platform_gateway.send_text_message(
                room_id=chat_id,
                content={
                    "msgtype": "m.text",
                    "body": (
                        "The meeting could not be scheduled due to technical"
                        " difficulties. I recommend you try again. If the problem"
                        " persists, you should report the issue to the system"
                        " administrator."
                    ),
                },
            )

    async def update_scheduled_meeting(
        self,
        user_id: str,
        chat_id: str,
        chat_thread_key: str,
    ) -> None:
        chat_thread = pickle.loads(
            self._keyval_storage_gateway.get(chat_thread_key, False)
        )

        action_parameters = await self._completion_gateway.get_completion(
            context=chat_thread["messages"]
            + [
                # Append info on tracked meetings
                {
                    "role": "system",
                    "content": self.get_scheduled_meetings_data(user_id),
                },
                {
                    "role": "user",
                    "content": (
                        "Give me the meeting update parameters as a JSON string."
                        ' Example: {"type": "virtual", "topic": "example", "date":'
                        ' "2024-01-01", "time": "15:00:00", "attendees":'
                        ' ["@u1:example.com", "@u2:example.com"], "location":'
                        ' "loc", "room_id": "room link"} Nothing else should be in'
                        " your response. The keys should be type, topic, date,"
                        " time, attendees, location, and room_id. Omit location if"
                        " it's a virtual meeting. room_id is the room link"
                        " associated with the meeting. The update will not work"
                        " without room_id. The attendees list should just include"
                        " the full platform formatted usernames."
                    ),
                },
            ],
            model=self._keyval_storage_gateway.get("groq_api_classification_model"),
            response_format="json_object",
        )
        meeting_params = dict(
            json.loads("{}" if action_parameters is None else action_parameters.content)
        )

        try:
            scheduled_meeting: Meeting = pickle.loads(
                self._keyval_storage_gateway.get(
                    SCHEDULED_MEETING_KEY.format(meeting_params["room_id"]), False
                )
            )
        except KeyError:
            self._logging_gateway.warning("default_meeting_service: KeyError.")
            traceback.print_exc()
            return

        meeting_update = Meeting(
            init=CreateMeetingDTO(
                meeting_params["type"],
                meeting_params["topic"],
                meeting_params["date"],
                meeting_params["time"],
                meeting_params["attendees"],
                user_id,
            ),
            expires_after=scheduled_meeting["expires_after"],
            room_id=scheduled_meeting["room_id"],
        )

        # If the meeting is in-person, we need to set the location.
        if not meeting_update.is_virtual():
            meeting_update.location = meeting_params["location"]

        meeting_request = UpdateScheduledMeetingRequest(meeting_update)

        # If the meeting topic has changed, we need to set an indicator.
        if (
            scheduled_meeting["topic"] != meeting_params["topic"]
            or scheduled_meeting["type"] != meeting_params["type"]
        ):
            meeting_request.change_topic = True

        update_meeting_response: UpdateScheduledMeetingResponse = (
            await self._meeting_updater.handle(meeting_request)
        )

        if not update_meeting_response.success:
            # Meeting parameters update was successful.
            await self._platform_gateway.send_text_message(
                room_id=chat_id,
                content={
                    "msgtype": "m.text",
                    "body": (
                        "The meeting details could not be updated due to technical"
                        " difficulties. I recommend you try again. If the problem"
                        " persists, you should report the issue to the system"
                        " administrator."
                    ),
                },
            )

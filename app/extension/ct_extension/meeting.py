"""Provides an implmentation of ICTExtension for managing meetings."""

__all__ = ["MeetingCTExtension"]

import json
import pickle
import traceback
from types import SimpleNamespace

from dependency_injector.wiring import inject, Provide
from nio import AsyncClient

from app.core.contract.completion_gateway import ICompletionGateway
from app.core.contract.ct_extension import ICTExtension
from app.core.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.core.contract.logging_gateway import ILoggingGateway
from app.core.contract.user_service import IUserService
from app.core.di import DIContainer

from app.extension.domain.entity.meeting import CreateMeetingDTO, Meeting
from app.extension.domain.use_case.cancel_scheduled_meeting import (
    CancelScheduledMeetingInteractor,
    CancelScheduledMeetingRequest,
    CancelScheduledMeetingResponse,
)
from app.extension.domain.use_case.schedule_meeting import (
    ScheduleMeetingInteractor,
    ScheduleMeetingRequest,
    ScheduleMeetingResponse,
)
from app.extension.domain.use_case.update_scheduled_meeting import (
    UpdateScheduledMeetingInteractor,
    UpdateScheduledMeetingRequest,
    UpdateScheduledMeetingResponse,
)

INPERSON_MEETING_DATA = (
    "{0} meeting secheduled for the {1} on {2} at {3}. The room link associated with"
    " this meeting is {4}. The topic is {5} and the attendees are {6}"
)

VIRTUAL_MEETING_DATA = (
    "{0} meeting using room {1}, secheduled for {2} at {3}. The topic is {4} and the"
    " attendees are {5}"
)


# pylint: disable=too-many-instance-attributes
class MeetingCTExtension(ICTExtension):
    """An implmentation of ICTExtension for managing meetings."""

    _triggers: list[str] = [
        "I'm arranging the requested meeting.",
        "I'm updating the specified meeting.",
        "I'm cancelling the specified meeting.",
    ]

    _scheduled_meeting_key = "scheduled_meeting:{0}"

    # pylint: disable=too-many-arguments
    @inject
    def __init__(
        self,
        client: AsyncClient = Provide[DIContainer.client],
        config: dict = Provide[DIContainer.config],
        completion_gateway: ICompletionGateway = Provide[
            DIContainer.completion_gateway
        ],
        keyval_storage_gateway: IKeyValStorageGateway = Provide[
            DIContainer.keyval_storage_gateway
        ],
        logging_gateway: ILoggingGateway = Provide[DIContainer.logging_gateway],
        user_service: IUserService = Provide[DIContainer.user_service],
    ) -> None:
        self._client = client
        self._config = SimpleNamespace(**config)
        self._completion_gateway = completion_gateway
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._user_service = user_service

        self._meeting_canceller = CancelScheduledMeetingInteractor(
            self._client,
            self._keyval_storage_gateway,
            self._scheduled_meeting_key,
            self._user_service,
        )
        self._meeting_scheduler = ScheduleMeetingInteractor(
            self._client,
            self._config,
            self._keyval_storage_gateway,
            self._scheduled_meeting_key,
            self._user_service,
        )
        self._meeting_updater = UpdateScheduledMeetingInteractor(
            self._client,
            self._keyval_storage_gateway,
            self._scheduled_meeting_key,
            self._user_service,
        )

        # Configure completion API.
        completion_api_prefix = self._config.gloria_completion_api_prefix
        classification_model = f"{completion_api_prefix}_api_classification_model"
        self._classification_model = config[classification_model]
        classification_temp = f"{completion_api_prefix}_api_classification_temp"
        self._classification_temp = config[classification_temp]
        completion_model = f"{completion_api_prefix}_api_completion_model"
        self._completion_model = config[completion_model]
        completion_temp = f"{completion_api_prefix}_api_completion_temp"
        self._completion_temp = config[completion_temp]

    @property
    def triggers(self) -> list[str]:
        return self._triggers

    async def process_message(
        self,
        message: str,
        _role: str,
        room_id: str,
        user_id: str,
        chat_thread_key: str,
    ) -> None:
        """Check assistant response for conversational triggers."""
        # If trigger detected to schedule meeting.
        if self._triggers[0] in message:
            await self.schedule_meeting(user_id, room_id, chat_thread_key)

        # If trigger detected to update scheduled meeting.
        elif self._triggers[1] in message:
            await self.update_scheduled_meeting(user_id, room_id, chat_thread_key)

        # If trigger detected to cancel meeting.
        elif self._triggers[2] in message:
            await self.cancel_scheduled_meeting(user_id, room_id, chat_thread_key)

    def get_system_context_data(self, user_id: str) -> list[dict]:
        return [
            {
                "role": "system",
                "content": (
                    "You will assist users in scheduling meetings. There are two types"
                    " of meetings you will assist with, virtual meetings and in-person"
                    " meetings. You must confirm which meeting type the user wants"
                    " before collecting any other data."
                ),
            },
            {
                "role": "system",
                "content": (
                    "For virtual meetings, you need to collect the date, time, topic,"
                    " and attendees."
                ),
            },
            {
                "role": "system",
                "content": (
                    "For in-person meetings, you need to collect the date, time, topic,"
                    " attendees, and location."
                ),
            },
            {
                "role": "system",
                "content": (
                    "Prompt the user for any information that is missing. If you are"
                    " given a day of the week or days such as today or tomorrow,"
                    " convert the to a date in the format %Y-%m-%d. When you have"
                    " collected all the required information, confirm it with the user."
                    " ensure you include the type of meeting in the confirmation. When"
                    " the user confirms the information, only say \"I'm arranging the"
                    ' requested meeting.", nothing else.'
                ),
            },
            {
                "role": "system",
                "content": (
                    "If you do not have any of the attendees in your contact list, ask"
                    " the user to confirm that you can go ahead and schedule the"
                    " meeting without that attendee, or advise them to have the missing"
                    " attendee register with you using your element username (state"
                    " your username). Always use the full names from your contact list"
                    " (with the username in parentheses) when confirming the attendees"
                    " with the user. Always include the user you are chatting with in"
                    " the list of attendees."
                ),
            },
            {
                "role": "system",
                "content": (
                    " When listing scheduled meetings for a user, ensure that you only"
                    " list meetings they are scheduled to attend, and do not duplicate"
                    " meeting information."
                ),
            },
            {
                "role": "system",
                "content": (
                    "If the user wants to update a scheduled meeting, you need to find"
                    " out which of the tracked meetings it is, show them the current"
                    " details, and then find out the parameters they wish to change."
                    " Confirm the changes with the user. When you have the required"
                    ' changes, only say "I\'m updating the specified meeting.", nothing'
                    " else."
                ),
            },
            {
                "role": "system",
                "content": (
                    "If the user wants to cancel (delete) a scheduled meeting, you need"
                    " to find out which of the tracked meetings it is, show them the"
                    " current details, and confirm that they want to cancel the"
                    " meeting. Ensure that you list the room link when confirming"
                    " cancellation.- When the user confirms cancelling the meeting,"
                    ' only say "I\'m cancelling the specified meeting", nothing else.'
                ),
            },
            {
                "role": "system",
                "content": self.get_scheduled_meetings_data(user_id),
            },
        ]

    async def cancel_scheduled_meeting(
        self,
        user_id: str,
        chat_id: str,
        chat_thread_key: str,
    ) -> None:
        """Cancel a scheduled meeting."""
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
            model=self._completion_model,
        )
        cancel_id = (
            "" if action_parameters is None else action_parameters.content.strip()
        )

        try:
            scheduled_meeting: Meeting = pickle.loads(
                self._keyval_storage_gateway.get(
                    self._scheduled_meeting_key.format(cancel_id), False
                )
            )
        except TypeError:
            self._logging_gateway.warning(
                "MeetingTriggeredServiceProvider.cancel_scheduled_meeting: TypeError."
            )
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
            await self._client.room_send(
                room_id=chat_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": (
                        "The meeting cancellation failed due to technical difficulties."
                        " I recommend you try again. If the problem persists, you"
                        " should report the issue to the system administrator."
                    ),
                },
            )

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

    async def schedule_meeting(
        self, user_id: str, chat_id: str, chat_thread_key: str
    ) -> None:
        """Schedule a meeting."""
        chat_thread = pickle.loads(
            self._keyval_storage_gateway.get(chat_thread_key, False)
        )
        action_parameters = await self._completion_gateway.get_completion(
            context=chat_thread["messages"]
            + [
                {
                    "role": "user",
                    "content": (
                        "Give the meeting parameters as a JSON string. Your response"
                        " should not contain any text other than the JSON string. The"
                        " keys should be type, topic, date, time, attendees, and"
                        " location. Omit location if it's a virtual meeting. The"
                        " attendees list should just include the full platform"
                        " formatted usernames. Date should be in the format %Y-%m-%d."
                    ),
                }
            ],
            model=self._completion_model,
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
            expires_after=int(self._config.gloria_meeting_expiry_time),
        )

        # If the meeting is in-person, we need to set the location.
        if meeting_params["type"] == "in-person":
            meeting_request.location = meeting_params["location"]

        schedule_meeting_response: ScheduleMeetingResponse = (
            await self._meeting_scheduler.handle(meeting_request)
        )

        # If scheduling the meeting failed.
        if not schedule_meeting_response.success:
            await self._client.room_send(
                room_id=chat_id,
                message_type="m.room.message",
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
        """Update a scheduled meeting."""
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
                        "Give me the meeting update parameters as a JSON string. Your"
                        " response should not contain any text other than the JSON"
                        " string. The keys should be type, topic, date, time,"
                        " attendees, location, and room_id. Omit location if it's a"
                        " virtual meeting. room_id is the room link associated with the"
                        " meeting. The update will not work without room_id. The"
                        " attendees list should just include the full platform"
                        " formatted usernames."
                    ),
                },
            ],
            model=self._completion_model,
            response_format="json_object",
        )
        meeting_params = dict(
            json.loads("{}" if action_parameters is None else action_parameters.content)
        )

        try:
            scheduled_meeting: Meeting = pickle.loads(
                self._keyval_storage_gateway.get(
                    self._scheduled_meeting_key.format(meeting_params["room_id"]), False
                )
            )
        except KeyError:
            self._logging_gateway.warning(
                "MeetingTriggeredServiceProvider.update_scheduled_meeting: KeyError."
            )
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
            await self._client.room_send(
                room_id=chat_id,
                message_type="m.room.message",
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

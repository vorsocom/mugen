"""Provides a Groq chat completion gateway."""

# https://console.groq.com/docs/api-reference#chat

import traceback
from typing import Optional
import pickle

from groq import AsyncGroq, GroqError

from app.contract.completion_gateway import ICompletionGateway
from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.logging_gateway import ILoggingGateway


INPERSON_MEETING_DATA = (
    "{0} meeting secheduled for the {1} on {2} at {3}. The room link associated with"
    " this meeting is {4}. The topic is {5} and the attendees are {6}"
)

VIRTUAL_MEETING_DATA = (
    "{0} meeting using room {1}, secheduled for {2} at {3}. The topic is {4} and the"
    " attendees are {5}"
)


class GroqCompletionGateway(ICompletionGateway):
    """A Groq chat compeltion gateway."""

    def __init__(
        self,
        api_key: str,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
    ) -> None:
        super().__init__()
        self._api = AsyncGroq(api_key=api_key)
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway

    @staticmethod
    def format_completion(response: Optional[str], default: str) -> str:
        """Format a completion response, returning a default value if it's None."""
        return default if response is None else response

    async def classify_message(
        self, message: str, model: str, response_format: str = "json_object"
    ) -> Optional[str]:
        response = None
        context = [
            {
                "role": "system",
                "content": (
                    "Classify the message based on if the user wants to do one of the"
                    " following:\n1. Search orders (classification=search_orders).\nIf"
                    " the user wants to search orders, you need to extract the subject"
                    " of the search which would be the name of a person, and the orders"
                    " event type which could include TOS, SOS, embodiment,"
                    " disembodiment, posting, appointment, allowances, leave, short"
                    " pass, exemption, marriage, AWOL, punishment, and forfeiture."
                    " \nYou have to return the extracted information as properly"
                    ' formatted JSON. For example, if the user instructs "Search orders'
                    ' for the last time John Smith was posted." your response would be'
                    ' {"classification": "search_orders", "subject": "John Smith",'
                    ' "event_type": "posting"}. If you are unable to classify the'
                    ' message just return {"classification": null}. For event_type, use'
                    " the stemmed version of the word. For example, the stem of posting"
                    " and posted is post. If you cannot determine the event_type, use"
                    " an empty string."
                ),
            },
            {"role": "user", "content": message},
        ]
        try:
            chat_completion = await self._api.chat.completions.create(
                messages=context, model=model, response_format={"type": response_format}
            )
            response = chat_completion.choices[0].message.content
        except GroqError:
            self._logging_gateway.warning(
                "An error was encountered while trying the Groq API."
            )
            traceback.print_exc()
        return response

    async def get_completion(
        self, context: list[dict], model: str, response_format: str = "text"
    ) -> Optional[str]:
        response = None
        try:
            chat_completion = await self._api.chat.completions.create(
                messages=context, model=model, response_format={"type": response_format}
            )
            response = chat_completion.choices[0].message.content
        except GroqError:
            self._logging_gateway.warning(
                "An error was encountered while trying the Groq API."
            )
            traceback.print_exc()

        return response

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

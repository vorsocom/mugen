"""Provides a Groq chat completion gateway."""

# https://console.groq.com/docs/api-reference#chat

import traceback
from typing import Optional

from groq import AsyncGroq, GroqError
from groq.types.chat import ChatCompletionMessage

from app.contract.completion_gateway import ICompletionGateway
from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.logging_gateway import ILoggingGateway


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

    async def get_chat_thread_classification(
        self,
        context: list[dict],
        message: str,
        model: str,
        response_format: str = "json_object",
    ) -> Optional[str]:
        response = None
        classification_context = [x for x in context if x["role"] == "user"]
        classification_context += [
            {
                "role": "system",
                "content": (
                    "Classify the next user message based on whether or not it is a"
                    " likely continuation of the conversation based on semantic"
                    " analysis of the previous user messages. Return your"
                    " classification as properly formatted JSON. For example, if the"
                    ' message is a continuation, return {"continuation": true},'
                    ' otherwise return {"continuation": false}. If you are unable to'
                    ' provide a continuation classification, return {"classification":'
                    " null}."
                ),
            }
        ]
        classification_context += [{"role": "user", "content": message}]
        try:
            chat_completion = await self._api.chat.completions.create(
                messages=classification_context,
                model=model,
                response_format={"type": response_format},
            )
            response = chat_completion.choices[0].message.content
        except GroqError:
            self._logging_gateway.warning(
                "GroqCompletionGateway.get_chat_thread_classification: An error was"
                " encountered while trying the Groq API."
            )
            traceback.print_exc()
        return response

    async def get_completion(
        self, context: list[dict], model: str, response_format: str = "text"
    ) -> Optional[ChatCompletionMessage]:
        response = None
        try:
            chat_completion = await self._api.chat.completions.create(
                messages=context, model=model, response_format={"type": response_format}
            )
            response = chat_completion.choices[0].message
            # self._logging_gateway.debug(
            #     f"tool calls: {chat_completion.choices[0].message}"
            # )
        except GroqError:
            self._logging_gateway.warning(
                "GroqCompletionGateway.get_completion: An error was encountered while"
                " trying the Groq API."
            )
            traceback.print_exc()

        return response

    async def get_rag_classification_gdf_knowledge(
        self, message: str, model: str, response_format: str = "json_object"
    ) -> Optional[str]:
        response = None
        context = [
            {
                "role": "system",
                "content": (
                    "Classify the message based on if the user wants to know something"
                    " about the Guyana Defence Force (GDF). If the user wants to know"
                    " something about the GDF, you have to return the extracted"
                    " information as properly formatted JSON. For example, if the user"
                    ' asks "Who is the head of the Guyana Defence Force?", you will'
                    ' return {"classification": "gdf_knowledge"}. If you are unable to'
                    ' classify the message just return {"classification": null}.'
                ),
            },
            {"role": "user", "content": message},
        ]
        try:
            chat_completion = await self._api.chat.completions.create(
                messages=context, model=model, response_format={"type": response_format}
            )
            response = chat_completion.choices[0].message.content
            # self._logging_gateway.debug(response)
        except GroqError:
            self._logging_gateway.warning(
                "GroqCompletionGateway.get_rag_classification_gdf_knowledge: An error"
                " was encountered while trying the Groq API."
            )
            traceback.print_exc()
        return response

    async def get_rag_classification_orders(
        self, message: str, model: str, response_format: str = "json_object"
    ) -> Optional[str]:
        response = None
        context = [
            {
                "role": "system",
                "content": (
                    "Classify the message based on if the user wants to search orders."
                    " If the user wants to search orders, you need to extract the"
                    " subject of the search which would be the name of a person, and"
                    " the orders event type which could include TOS, SOS, embodied,"
                    " disembodied, posted, appointed, allowances, leave, short pass,"
                    " exemption, marriage, AWOL, punishment, and forfeiture. You have"
                    " to return the extracted information as properly formatted JSON."
                    ' For example, if the user instructs "Search orders for the last'
                    ' time John Smith was posted." your response would be'
                    ' {"classification": "search_orders", "subject": "John Smith",'
                    ' "event_type": "posted"}. If you are unable to classify the'
                    ' message just return {"classification": null}. If you cannot'
                    " determine the event_type, use an empty string."
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
                "GroqCompletionGateway.get_rag_classification_orders: An error was"
                " encountered while trying the Groq API."
            )
            traceback.print_exc()
        return response

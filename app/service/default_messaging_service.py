"""Provides an implementation of IMessagingService."""

__all__ = ["DefaultMessagingService"]

from datetime import datetime
import json
import pickle
from typing import Mapping
import uuid

from nio import AsyncClient

from app.contract.completion_gateway import ICompletionGateway
from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.knowledge_retrieval_gateway import IKnowledgeRetrievalGateway
from app.contract.logging_gateway import ILoggingGateway
from app.contract.meeting_service import IMeetingService
from app.contract.messaging_service import IMessagingService
from app.contract.platform_gateway import IPlatformGateway

SCHEDULED_MEETING_KEY = "scheduled_meeting:{0}"


class DefaultMessagingService(IMessagingService):
    """The default implementation of IMessagingService."""

    def __init__(
        self,
        client: AsyncClient,
        completion_gateway: ICompletionGateway,
        keyval_storage_gateway: IKeyValStorageGateway,
        knowledge_retrieval_gateway: IKnowledgeRetrievalGateway,
        logging_gateway: ILoggingGateway,
        platform_gateway: IPlatformGateway,
        meeting_service: IMeetingService,
    ) -> None:
        self._client = client
        self._completion_gateway = completion_gateway
        self._keyval_storage_gateway = keyval_storage_gateway
        self._knowledge_retrieval_gateway = knowledge_retrieval_gateway
        self._logging_gateway = logging_gateway
        self._platform_gateway = platform_gateway
        self._meeting_service = meeting_service

    async def handle_text_message(
        self,
        room_id: str,
        message_id: str,
        sender: str,
        content: str,
        known_users_list_key: str,
    ) -> None:
        # Set the room read marker to indicate that the assistant has read the
        # message.
        await self._client.room_read_markers(room_id, message_id, message_id)

        # Get the attention thread.
        attention_thread_key = await self._get_attention_thread_key(room_id, content)

        # Initialise lists to store chat history.
        attention_thread: Mapping[str, str | list[Mapping[str, str]]] = {"messages": []}

        # Load previous history from storage if it exists.
        if self._keyval_storage_gateway.has_key(attention_thread_key):
            attention_thread = pickle.loads(
                self._keyval_storage_gateway.get(attention_thread_key, False)
            )
        else:
            attention_thread["created"] = datetime.now().strftime("%s")
        # self._logging_gateway.debug(attention_thread)

        # Send user message to assistant with history.
        attention_thread["messages"].append({"role": "user", "content": content})

        # Add chat history and system context to completion context.
        completion_context = []
        completion_context += attention_thread["messages"]
        completion_context += self._get_system_context(known_users_list_key, sender)
        completion_context += await self._get_rag_context(content)

        # Get assistant response based on chat history, system context, and RAG data.
        chat_completion = await self._completion_gateway.get_completion(
            context=completion_context,
            model=self._keyval_storage_gateway.get("groq_api_completion_model"),
        )

        # If the chat completion attempt failed, set it to "Error" so that the user
        # will be aware of the failure.
        if chat_completion is None:
            chat_completion = "Error"

        # Persist chat history.
        attention_thread["messages"].append(
            {"role": "assistant", "content": chat_completion}
        )
        attention_thread["last_saved"] = datetime.now().strftime("%s")
        self._keyval_storage_gateway.put(
            attention_thread_key, pickle.dumps(attention_thread)
        )

        # Send assistant response to the user.
        await self._client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": chat_completion,
            },
        )

        await self._meeting_service.handle_assistant_response(
            chat_completion, sender, room_id, attention_thread_key
        )

        return

    async def _get_attention_thread_key(self, room_id: str, message: str) -> str:
        """Get the chat thread that the message is related to."""
        # Get the key to retrieve the list of chat threads for this room.
        chat_threads_list_key = f"chat_threads_list:{room_id}"

        # If the key does not exist...
        if not self._keyval_storage_gateway.has_key(chat_threads_list_key):
            # This is the first message in this room.
            # Create a new chat thread key and return it as the attention thread key.
            self._logging_gateway.debug("New chat. Generating new chat thread.")
            return self._get_new_chat_thread_key(chat_threads_list_key)

        # else.
        # The key does exist.
        chat_threads_list = pickle.loads(
            self._keyval_storage_gateway.get(chat_threads_list_key, False)
        )

        # Check each thread for relevance to the message.
        hits = []
        for item in chat_threads_list:
            chat_thread = pickle.loads(self._keyval_storage_gateway.get(item, False))
            self._logging_gateway.debug(
                "Checking user message for relevance to thread."
            )
            classification = (
                await self._completion_gateway.get_chat_thread_classification(
                    context=chat_thread["messages"],
                    message=message,
                    model=self._keyval_storage_gateway.get(
                        "groq_api_classification_model"
                    ),
                )
            )

            if classification is None:
                self._logging_gateway.warning("Error in releavnce check.")
                continue

            classification: dict = json.loads(classification)

            if "classification" in classification.keys():
                self._logging_gateway.debug("Relevance could not be determined.")
                continue

            if classification["continuation"] is False:
                self._logging_gateway.debug("Message not relevant to thread.")
                continue

            self._logging_gateway.debug("Message is relevant to thread.")
            hits.append(item)

        self._logging_gateway.debug(f"Hits: {hits}")

        if len(hits) == 0:
            self._logging_gateway.debug("No relevant threads found. Starting new one.")
            return self._get_new_chat_thread_key(chat_threads_list_key)

        if len(hits) == 1:
            self._logging_gateway.debug("One relevant thread found. Returning the key.")
            return hits[0]

        # If we get to this point it means we had multiple hits for relevant threads.
        # Start a new thread to avoid selecting the wrong one.
        self._logging_gateway.debug(
            "Multiple relevant threads found. Starting new one to avoid decision error."
        )
        return self._get_new_chat_thread_key(chat_threads_list_key)

    def _get_new_chat_thread_key(self, chat_threads_list_key: str) -> str:
        """Generate a new chat thread key."""
        chat_thread_key = f"chat_thread:{uuid.uuid1()}"
        self._keyval_storage_gateway.put(
            chat_threads_list_key, pickle.dumps([chat_thread_key])
        )
        return chat_thread_key

    async def _get_rag_context(self, message: str) -> list[dict]:
        """Get a list of strings representing knowledge pulled from an RAG source."""
        classification = await self._completion_gateway.get_rag_classification(
            message=message,
            model=self._keyval_storage_gateway.get("groq_api_classification_model"),
        )

        knowledge_docs: list[str] = []
        if classification is not None:
            instruct = json.loads(classification)
            # self._logging_gateway.debug(json.dumps(instruct, indent=4))
            match instruct["classification"]:
                case "search_orders":
                    hits = await self._knowledge_retrieval_gateway.search_similar(
                        "mil_orders", f'{instruct["subject"]} {instruct["event_type"]}'
                    )
                    if len(hits) > 0:
                        self._logging_gateway.debug(
                            "default_messaging_gateway: similarity search hits -"
                            f" {len(hits)}"
                        )
                        hit_str = (
                            "In {0} Orders Serial {1} dated {2}, paragraph {3}"
                            " states: {4}"
                        )
                        knowledge_docs = [
                            hit_str.format(
                                x.payload["type"],
                                x.payload["serial"],
                                x.payload["date"],
                                x.payload["paragraph"],
                                x.payload["data"],
                            )
                            for x in hits
                        ]

                case _:
                    pass
        # self._logging_gateway.debug(f"default_messaging_service: RAG {knowledge_docs}")

        context = []
        if len(knowledge_docs) > 0:
            context.append(
                {
                    "role": "system",
                    "content": " || ".join(knowledge_docs),
                }
            )
            context.append(
                {
                    "role": "system",
                    "content": (
                        "When giving information from orders, always cite the serial,"
                        " paragraph number, and date of publication. Do not make up any"
                        " information. If you do not have any information, say so."
                    ),
                }
            )
        return context

    def _get_system_context(self, known_users_list_key: str, sender: str) -> list[dict]:
        """Return a list of system messages to add context to user message."""
        # Load known users list.
        known_users_list = pickle.loads(
            self._keyval_storage_gateway.get(known_users_list_key, False)
        )

        context = []
        # Append date and time to context.
        context.append(
            {
                "role": "system",
                "content": "The day of the week, date, and time are "
                + datetime.now().strftime("%A, %Y-%m-%d, %H:%M:%S")
                + ", respectively",
            }
        )

        # Append assistant persona to context.
        context.append(
            {
                "role": "system",
                "content": self._keyval_storage_gateway.get("matrix_assistant_persona"),
            }
        )

        # Append user information to context.
        sender_name = known_users_list[sender]["displayname"] + " (" + sender + ")"
        context.append(
            {
                "role": "system",
                "content": "You are chatting with " + sender_name,
            }
        )

        # Append known users information to context.
        context.append(
            {
                "role": "system",
                "content": "The list of known users on the platform are: "
                + ",".join(
                    [
                        known_users_list[k]["displayname"] + " (" + k + ")"
                        for (k, _) in known_users_list.items()
                    ]
                )
                + ".",
            }
        )

        # Append information on tracked meetings to context.
        context.append(
            {
                "role": "system",
                "content": self._meeting_service.get_scheduled_meetings_data(sender),
            }
        )

        return context

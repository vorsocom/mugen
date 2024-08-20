"""Provides an implementation of IMessagingService."""

__all__ = ["DefaultMessagingService"]

from datetime import datetime
import json
import pickle
import types
from typing import Mapping
import uuid

from groq.types.chat import ChatCompletionMessage
from nio import AsyncClient
from qdrant_client.models import ScoredPoint

from app.contract.completion_gateway import ICompletionGateway
from app.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.contract.knowledge_retrieval_gateway import IKnowledgeRetrievalGateway
from app.contract.logging_gateway import ILoggingGateway
from app.contract.meeting_service import IMeetingService
from app.contract.messaging_service import IMessagingService
from app.contract.platform_gateway import IPlatformGateway
from app.contract.user_service import IUserService

CHAT_THREAD_VERSION: int = 1

CHAT_THREADS_LIST_VERSION: int = 1

RAG_CACHE_GDF_KNOWLEDGE_KEY: str = "rag_cache_gdf_knowledge"

RAG_CACHE_ORDERS_KEY: str = "rag_cache_orders"

SCHEDULED_MEETING_KEY: str = "scheduled_meeting:{0}"


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
        user_service: IUserService,
    ) -> None:
        self._client = client
        self._completion_gateway = completion_gateway
        self._keyval_storage_gateway = keyval_storage_gateway
        self._knowledge_retrieval_gateway = knowledge_retrieval_gateway
        self._logging_gateway = logging_gateway
        self._platform_gateway = platform_gateway
        self._meeting_service = meeting_service
        self._user_service = user_service

    async def handle_text_message(
        self,
        room_id: str,
        message_id: str,
        sender: str,
        content: str,
    ) -> None:
        # Set the room read marker to indicate that the assistant has read the
        # message.
        await self._client.room_read_markers(room_id, message_id, message_id)

        if content.strip() == "//clear.":
            # Empty attention thread.
            await self._get_attention_thread_key(room_id, "", True)

            # Clear RAG caches.
            if self._keyval_storage_gateway.has_key(RAG_CACHE_GDF_KNOWLEDGE_KEY):
                self._keyval_storage_gateway.remove(RAG_CACHE_GDF_KNOWLEDGE_KEY)

            if self._keyval_storage_gateway.has_key(RAG_CACHE_ORDERS_KEY):
                self._keyval_storage_gateway.remove(RAG_CACHE_ORDERS_KEY)
            return

        # Get the attention thread key.
        attention_thread_key = await self._get_attention_thread_key(room_id, content)

        # Initialise lists to store chat history.
        attention_thread: Mapping[str, str | list[Mapping[str, str]]] = {"messages": []}

        # Load previous history from storage if it exists.
        if self._keyval_storage_gateway.has_key(attention_thread_key):
            attention_thread = pickle.loads(
                self._keyval_storage_gateway.get(attention_thread_key, False)
            )
            # Ensure that older threads are versioned.
            # This can be removed after the application stabalises.
            if "version" not in attention_thread.keys():
                attention_thread["version"] = CHAT_THREAD_VERSION
        else:
            attention_thread["version"] = CHAT_THREAD_VERSION
            attention_thread["created"] = datetime.now().strftime("%s")

        # self._logging_gateway.debug(f"attention_thread: {attention_thread}")

        completion_context = []

        # Add system context to completion context.
        completion_context += self._get_system_context(sender)

        # Add chat history to completion context.
        attention_thread["messages"].append({"role": "user", "content": content})
        completion_context += attention_thread["messages"]

        # Execute RAG pipelines and get data if any was found.
        # If the user message did not trigger an RAG query, the information from the
        # last successful query will still be cached.
        await self._get_rag_context_gdf_knowledge(content)
        if self._keyval_storage_gateway.has_key(RAG_CACHE_GDF_KNOWLEDGE_KEY):
            gdfk_cache = pickle.loads(
                self._keyval_storage_gateway.get(RAG_CACHE_GDF_KNOWLEDGE_KEY, False)
            )
            # self._logging_gateway.debug(f"gdfk_cache: {gdfk_cache}")
            completion_context += gdfk_cache
        await self._get_rag_context_orders(sender, content)
        if self._keyval_storage_gateway.has_key(RAG_CACHE_ORDERS_KEY):
            orders_cache = pickle.loads(
                self._keyval_storage_gateway.get(RAG_CACHE_ORDERS_KEY, False)
            )
            # self._logging_gateway.debug(f"orders_cache: {orders_cache}")
            completion_context += orders_cache

        # Add system suffix context to completion context.
        # completion_context += self._get_system_context_suffix(sender)

        # self._logging_gateway.debug(json.dumps(completion_context, indent=4))
        # Get assistant response based on chat history, system context, and RAG data.
        self._logging_gateway.debug("Get completion.")
        chat_completion: ChatCompletionMessage = (
            await self._completion_gateway.get_completion(
                context=completion_context,
                model=self._keyval_storage_gateway.get("groq_api_completion_model"),
            )
        )

        # If the chat completion attempt failed, set it to "Error" so that the user
        # will be aware of the failure.
        if chat_completion is None:
            self._logging_gateway.debug("chat_completion: None.")
            chat_completion = types.SimpleNamespace()
            chat_completion.content = "Error"

        assistant_response = chat_completion.content

        # Manage metadata returned by the LLM.
        # Save current thread first.
        self._save_chat_thread(attention_thread_key, attention_thread)

        # Check for start task indicator.
        if "[task]" in assistant_response:
            self._logging_gateway.debug("[task] detected.")
            await self._get_attention_thread_key(room_id, "", True, True)
            assistant_response = assistant_response.replace("[task]", "").strip()
            attention_thread["messages"].append({"role": "system", "content": "[task]"})

        # Check for end task indicator.
        if "[end-task]" in assistant_response:
            self._logging_gateway.debug("[end-task] detected.")
            # Only refresh thread if the response doesn't contain
            # a conversational trigger.
            if (
                len(
                    [
                        x
                        for x in self._meeting_service.get_meeting_triggers()
                        if x in assistant_response
                    ]
                )
                == 0
            ):
                await self._get_attention_thread_key(room_id, "", True)
            # self._logging_gateway.debug(assistant_response)
            assistant_response = assistant_response.replace("[end-task]", "").strip()

        if assistant_response != "":
            # Persist chat history.
            self._logging_gateway.debug("Persist attention thread.")
            attention_thread["messages"].append(
                {
                    "role": "assistant",
                    "content": assistant_response,
                }
            )

            # Send assistant response to the user.
            self._logging_gateway.debug("Send response to user.")
            await self._platform_gateway.send_text_message(
                room_id=room_id,
                content={
                    "msgtype": "m.text",
                    "body": assistant_response,
                },
            )

            self._logging_gateway.debug(
                "Pass response to meeting service for processing."
            )
            await self._meeting_service.handle_assistant_response(
                assistant_response, sender, room_id, attention_thread_key
            )

        self._save_chat_thread(attention_thread_key, attention_thread)
        return

    async def _get_attention_thread_key(
        self,
        room_id: str,
        message: str,
        refresh: bool = False,
        start_task: bool = False,
    ) -> str:
        """Get the chat thread that the message is related to."""
        # Get the key to retrieve the list of chat threads for this room.
        chat_threads_list_key = f"chat_threads_list:{room_id}"

        # If chat threads list key does not exist.
        if not self._keyval_storage_gateway.has_key(chat_threads_list_key):
            # This is the first message in this room.
            # Create a new chat thread key and return it as the attention thread key.
            self._logging_gateway.debug("New chat. Generating new list and new thread.")
            return self._get_new_chat_thread_key(chat_threads_list_key, True)

        # else:
        # The key does exist.
        chat_threads_list = pickle.loads(
            self._keyval_storage_gateway.get(chat_threads_list_key, False)
        )

        if refresh:
            attention_thread = pickle.loads(
                self._keyval_storage_gateway.get(
                    chat_threads_list["attention_thread"], False
                )
            )
            if start_task:
                self._logging_gateway.debug("Refreshing attention thread (Start task).")
                attention_thread["messages"] = attention_thread["messages"][-1:]
            else:
                self._logging_gateway.debug("Refreshing attention thread (other).")
                attention_thread["messages"] = []
            self._save_chat_thread(
                chat_threads_list["attention_thread"], attention_thread
            )
            # self._logging_gateway.debug(attention_thread["messages"])
            return chat_threads_list["attention_thread"]

        if "attention_thread" in chat_threads_list.keys():
            self._logging_gateway.debug(
                "Returning current attention thread for testing."
            )
            return chat_threads_list["attention_thread"]

        # Migrate old lists.
        if isinstance(chat_threads_list, list):
            chat_threads_list = {"threads": chat_threads_list}

        self._logging_gateway.debug(f"chat_threads_list: {chat_threads_list}")

        # Check each thread for relevance to the message.
        hits = []
        for item in chat_threads_list["threads"]:
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
            return self._get_new_chat_thread_key(chat_threads_list_key, False)

        if len(hits) == 1:
            self._logging_gateway.debug("One relevant thread found. Returning the key.")
            self._set_attention_thread(chat_threads_list_key, hits[0])
            return hits[0]

        # If we get to this point it means we had multiple hits for relevant threads.
        # Start a new thread to avoid selecting the wrong one.
        self._logging_gateway.debug("Multiple relevant threads found.")

        # If the current attention thread is in the hit list, just return that.
        if "attention_thread" in chat_threads_list.keys():
            if chat_threads_list["attention_thread"] in hits:
                self._logging_gateway.debug("Returning the current attention thread.")
                return chat_threads_list["attention_thread"]

        # else:
        # If the attention thread is not in the hit list, return a new thread to avoid
        # selecting the wrong one.
        self._logging_gateway.debug("Returning a new attention thread.")
        return self._get_new_chat_thread_key(chat_threads_list_key, False)

    def _get_new_chat_thread_key(
        self, chat_threads_list_key: str, new_list: bool
    ) -> str:
        """Generate a new chat thread key."""
        # Generate new key.
        self._logging_gateway.debug("Generating new chat thread key.")
        key = f"chat_thread:{uuid.uuid1()}"

        chat_threads_list = {}
        # If its a new thread list.
        if new_list:
            # Create a new thread list, and make the new thread the attention thread.
            self._logging_gateway.debug("Creating new thread list.")
            chat_threads_list["version"] = CHAT_THREADS_LIST_VERSION
            chat_threads_list["attention_thread"] = key
            chat_threads_list["threads"] = [key]
        else:
            # The thread list exists.
            self._logging_gateway.debug("Load existing thread list.")
            chat_threads_list = pickle.loads(
                self._keyval_storage_gateway.get(chat_threads_list_key, False)
            )

            # Migrate old lists.
            if isinstance(chat_threads_list, list):
                self._logging_gateway.debug("Migrate old thread list to new format.")
                chat_threads_list = {"threads": chat_threads_list}

            if "version" not in chat_threads_list.keys():
                chat_threads_list["version"] = CHAT_THREADS_LIST_VERSION

            # Set new key as attention thread and append it to the threads list.
            chat_threads_list["attention_thread"] = key
            chat_threads_list["threads"].append(key)

        # Persist thread list.
        self._keyval_storage_gateway.put(
            chat_threads_list_key, pickle.dumps(chat_threads_list)
        )
        return key

    async def _get_rag_context_gdf_knowledge(self, message: str) -> None:
        """Get a list of strings representing knowledge pulled from an RAG source."""
        self._logging_gateway.debug("Processing GDF Knowledge RAG pipeline.")
        gdfk_classification = (
            await self._completion_gateway.get_rag_classification_gdf_knowledge(
                message=message,
                model=self._keyval_storage_gateway.get("groq_api_classification_model"),
            )
        )

        knowledge_docs: list[str] = []
        if gdfk_classification is not None:
            instruct = json.loads(gdfk_classification)
            # self._logging_gateway.debug(f"instruct: {instruct}")
            if instruct["classification"] == "gdf_knowledge":
                hits: list[ScoredPoint] = (
                    await self._knowledge_retrieval_gateway.search_similar(
                        "guyana_defence_force", "gdf_knowledge", message, "should"
                    )
                )
                if len(hits) > 0:
                    self._logging_gateway.debug(
                        "default_messaging_gateway: similarity search hits -"
                        f" {len(hits)}"
                    )
                    for hit in hits:
                        if "source" in hit.payload.keys():
                            knowledge_docs.append(
                                f'Section {hit.payload["section"]} of'
                                f' {hit.payload["chapter"]} of the'
                                f' {hit.payload["source"]} states:'
                                f' {hit.payload["data"]}'
                            )
                        else:
                            knowledge_docs.append(hit.payload["data"])

                # self._logging_gateway.debug(f"default_messaging_service: RAG {knowledge_docs}")

                if len(knowledge_docs) == 0:
                    knowledge_docs.append(
                        "No relevant information found in your GDF knowledge base. Do"
                        " not make up any information."
                    )

                context = []
                context.append(
                    {
                        "role": "system",
                        "content": " || ".join(knowledge_docs),
                    }
                )
                self._keyval_storage_gateway.put(
                    RAG_CACHE_GDF_KNOWLEDGE_KEY, pickle.dumps(context)
                )

    async def _get_rag_context_orders(self, sender: str, message: str) -> None:
        """Get a list of strings representing knowledge pulled from an RAG source."""
        self._logging_gateway.debug("Processing Orders RAG pipeline.")
        user_dn = self._user_service.get_user_display_name(sender)
        orders_classification = (
            await self._completion_gateway.get_rag_classification_orders(
                user=user_dn,
                message=message,
                model=self._keyval_storage_gateway.get("groq_api_classification_model"),
            )
        )

        knowledge_docs: list[str] = []
        if orders_classification is not None:
            instruct = json.loads(orders_classification)
            # self._logging_gateway.debug(json.dumps(instruct, indent=4))
            if instruct["classification"] == "search_orders":
                hits = await self._knowledge_retrieval_gateway.search_similar(
                    "guyana_defence_force",
                    "orders",
                    f'{instruct["subject"]} {instruct["event_type"]}',
                )
                if len(hits) > 0:
                    self._logging_gateway.debug(
                        "default_messaging_gateway: similarity search hits -"
                        f" {len(hits)}"
                    )
                    hit_str = (
                        "In {0} Orders Serial {1} dated {2}, paragraph {3} states: {4}"
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

                # self._logging_gateway.debug(f"default_messaging_service: RAG {knowledge_docs}")

                if len(knowledge_docs) == 0:
                    knowledge_docs.append(
                        "No relevant information found in your orders search. Do not"
                        " make up any information."
                    )

                context = []
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
                            "When giving information from orders, always cite the"
                            " serial, paragraph number, and date of publication."
                        ),
                    }
                )
                self._keyval_storage_gateway.put(
                    RAG_CACHE_ORDERS_KEY, pickle.dumps(context)
                )

    def _get_system_context(self, sender: str) -> list[dict]:
        """Return a list of system messages to add context to user message."""
        context = []
        known_users_list = self._user_service.get_known_users_list()

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
        context.append(
            {
                "role": "system",
                "content": (
                    "You are chatting with"
                    f" {self._user_service.get_user_display_name(sender)} ({sender})."
                    " Refer to this user by their first name unless otherwise"
                    " instructed."
                ),
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

        # Append meeting handling instructions.
        context.append(
            {
                "role": "system",
                "content": (
                    "One of your tasks, among many, is scheduling meetings. Your rules"
                    " for setting up meetings are:- Do not schedule meetings in the"
                    " past.- Do not update meetings in the past unless the update is to"
                    " move the date and time of the meeting to the future.- Find out if"
                    " the user wants to schedule a virtual or in-person meeting.- If"
                    " the user wants a virtual meeting on Element, you need to find out"
                    " the topic, date, time, and attendees. If the user wants an"
                    " in-person meeting, you need to find out the topic, date, time,"
                    " location, and attendees. Prompt the user for any parameters that"
                    " are missing. If you are given a day of the week as the date,"
                    " convert it to a date in the format 2024-01-01 and confirm that"
                    " date with the user.- When you have collected all the required"
                    " parameters, confirm them with the user.- When the user confirms,"
                    ' say "I\'m arranging the requested meeting."- If you do not have'
                    " any of the attendees in your contact list, ask the user to"
                    " confirm that you can go ahead and schedule the meeting without"
                    " that attendee, or advise them to have the missing attendee"
                    " register with you using your element username (state your"
                    " username).- Always use the full names from your contact list"
                    " (with the username) when confirming the attendees with the user.-"
                    " Always include the user you are chatting with in the list of"
                    " attendees.- Do not give the asssociated room link for the meeting"
                    " when confirming that a meeting has been sheduled. The user should"
                    " request it if they need it.- Output room links on a new line by"
                    " themselves, without any characters before or after the link. This"
                    " is important to avoid breaking the links.- Do not make up"
                    " (hallucinate) room links. Only use those from your list of"
                    " tracked meetings.- When listing scheduled meetings for a user,"
                    " ensure that you only list meetings they are scheduled to attend,"
                    " and do not duplicate meeting information.- If the user wants to"
                    " update a scheduled meeting, you need to find out which of the"
                    " tracked meetings it is, show them the current details, and then"
                    " find out the parameters they wish to change.- Confirm the changes"
                    " with the user.- When you have the required changes, say \"I'm"
                    ' updating the specified meeting."- If changing a virtual meeting'
                    " to an in-person meeting, the room link remains the same for the"
                    " in-person meeting.- If the user wants to cancel (delete) a"
                    " scheduled meeting, you need to find out which of the tracked"
                    " meetings it is, show them the current details, and confirm that"
                    " they want to cancel the meeting. Ensure that you list the room"
                    " link when confirming cancellation.- When the user confirms"
                    " cancelling the meeting, say \"I'm cancelling the specified"
                    " meeting.These are your instructions for your contact list:"
                ),
            }
        )

        context.append(
            {
                "role": "system",
                "content": (
                    "Always output room links on a separate line from the rest of the"
                    " text."
                ),
            }
        )

        # Append information on tracked meetings to context.
        context.append(
            {
                "role": "system",
                "content": self._meeting_service.get_scheduled_meetings_data(sender),
            }
        )

        # Append instructions to detect end of conversation
        context.append(
            {
                "role": "system",
                "content": (
                    "Your primary role is to help  the user complete tasks. If the user"
                    " sends you a new message that is not a follow-up to the previous"
                    " task, the user's message asks a new question, requests a new"
                    " action, or changes the topic, consider it an indicator of a new"
                    " task. Do not consider messages containing only a simple greeting,"
                    ' like "hello" or only a stop-word, such as "ok", an indicator of a'
                    " new task. When you detect a new task, prefix your message with"
                    " [task], skip a line, then add your response. The square backets"
                    " are important. Never use anything other than square brackets!. If"
                    " [task] already appears in your chat history with the user, do not"
                    " add it to any new messages."
                ),
            }
        )
        context.append(
            {
                "role": "system",
                "content": (
                    "A task has ended if you've completed a requested action, answered"
                    " a question not likely to have a follow-up message, or reached a"
                    " natural conclusion to the task. Also consider a task complete if"
                    " the user thanks you, indicates that they no longer need"
                    " assistance, or explicitly cancels the task. Do not consider"
                    ' messages containing only a stop-word such as "ok" an indicator'
                    " of the end of a task. When you detect the end of a task, write"
                    " your response, skip a line, and add [end-task]. Again, the square"
                    " brackets are important!. Your message to end a task should"
                    " never contain just [end-task] only, say something!"
                ),
            }
        )

        return context

    def _save_chat_thread(self, key: str, thread: dict) -> None:
        """Save an attention thread."""
        thread["last_saved"] = datetime.now().strftime("%s")
        self._keyval_storage_gateway.put(key, pickle.dumps(thread))

    def _set_attention_thread(
        self, chat_threads_list_key: str, attention_thread: str
    ) -> None:
        """Set the attention thread in a chat threads list."""
        if self._keyval_storage_gateway.has_key(chat_threads_list_key):
            # Load list.
            chat_threads_list = pickle.loads(
                self._keyval_storage_gateway.get(chat_threads_list_key, False)
            )

            # Migrate old lists to new format if necessary.
            if isinstance(chat_threads_list, list):
                self._logging_gateway.debug("Migrate old thread list to new format.")
                chat_threads_list = {"threads": chat_threads_list}

            chat_threads_list["attention_thread"] = attention_thread

            # Persist thread list.
            self._keyval_storage_gateway.put(
                chat_threads_list_key, pickle.dumps(chat_threads_list)
            )

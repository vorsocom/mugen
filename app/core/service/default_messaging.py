"""Provides an implementation of IMessagingService."""

__all__ = ["DefaultMessagingService"]

from datetime import datetime
import pickle
from types import SimpleNamespace
from typing import Mapping
import uuid

from app.core.contract.completion_gateway import ICompletionGateway
from app.core.contract.keyval_storage_gateway import IKeyValStorageGateway
from app.core.contract.logging_gateway import ILoggingGateway
from app.core.contract.messaging_service import IMessagingService
from app.core.contract.rag_extension import IRAGExtension
from app.core.contract.ct_extension import ICTExtension
from app.core.contract.user_service import IUserService

CHAT_THREAD_VERSION: int = 1

CHAT_THREADS_LIST_VERSION: int = 1


# pylint: disable=too-many-instance-attributes
class DefaultMessagingService(IMessagingService):
    """The default implementation of IMessagingService."""

    _ct_extensions: list[ICTExtension] = []

    _rag_extensions: list[IRAGExtension] = []

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        config: dict,
        completion_gateway: ICompletionGateway,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
        user_service: IUserService,
    ) -> None:
        self._config = SimpleNamespace(**config)
        self._completion_gateway = completion_gateway
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._user_service = user_service

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

    # pylint: disable=too-many-branches
    # pylint: disable=too-many-statements
    async def handle_text_message(
        self,
        room_id: str,
        sender: str,
        content: str,
    ) -> str | None:
        if content.strip() == "//clear.":
            # Empty attention thread.
            await self._get_attention_thread_key(room_id, "", True)

            # Clear RAG caches.
            for rag_ext in self._rag_extensions:
                if self._keyval_storage_gateway.has_key(rag_ext.cache_key):
                    self._keyval_storage_gateway.remove(rag_ext.cache_key)
            return "PUC executed."

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
        # If the user message did not trigger an RAG queries, the information from
        # previous successful queries will still be cached.
        for rag_ext in self._rag_extensions:
            await rag_ext.retrieve(sender, content)
            if self._keyval_storage_gateway.has_key(rag_ext.cache_key):
                rp_cache = pickle.loads(
                    self._keyval_storage_gateway.get(
                        rag_ext.cache_key,
                        False,
                    )
                )
                completion_context += rp_cache

        # self._logging_gateway.debug(json.dumps(completion_context, indent=4))
        # Get assistant response based on chat history, system context, and RAG data.
        self._logging_gateway.debug("Get completion.")
        chat_completion = await self._completion_gateway.get_completion(
            context=completion_context,
            model=self._completion_model,
            temperature=float(self._completion_temp),
        )

        # If the chat completion attempt failed, set it to "Error" so that the user
        # will be aware of the failure.
        if chat_completion is None:
            self._logging_gateway.debug("chat_completion: None.")
            chat_completion = SimpleNamespace()
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
            trigger_hits = 0
            for ct_ext in self._ct_extensions:
                for trigger in ct_ext.triggers:
                    if trigger in assistant_response:
                        trigger_hits += 1

            if trigger_hits == 0:
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

            self._logging_gateway.debug(
                "Pass response to triggered services for processing."
            )
            for ct_ext in self._ct_extensions:
                await ct_ext.process_message(
                    assistant_response,
                    "assistant",
                    room_id,
                    sender,
                    attention_thread_key,
                )
        else:
            self._logging_gateway.debug("Empty response.")

        self._save_chat_thread(attention_thread_key, attention_thread)
        return assistant_response

    def register_ct_extension(self, ext: ICTExtension) -> None:
        self._ct_extensions.append(ext)

    def register_rag_extension(self, ext: IRAGExtension) -> None:
        self._rag_extensions.append(ext)

    async def _get_attention_thread_key(
        self,
        room_id: str,
        _message: str,
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
                "content": self._config.assistant_persona,
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

        # Append information from triggered service providers to context.
        for ct_ext in self._ct_extensions:
            context += ct_ext.get_system_context_data(sender)

        # Append instructions to detect start and end of conversations.
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
                    " assistance, or explicitly cancels the task. When you detect the"
                    " end of a task, write your response, skip a line, and add"
                    " [end-task]. Again, the square brackets are important!. Your"
                    " message to end a task should never contain just [end-task] only,"
                    " say something!"
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

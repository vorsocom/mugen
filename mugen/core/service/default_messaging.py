"""Provides an implementation of IMessagingService."""

__all__ = ["DefaultMessagingService"]

import asyncio
from datetime import datetime
import pickle
from types import SimpleNamespace
from typing import Mapping
import uuid

from mugen.core.contract.completion_gateway import ICompletionGateway
from mugen.core.contract.ct_extension import ICTExtension
from mugen.core.contract.ctx_extension import ICTXExtension
from mugen.core.contract.keyval_storage_gateway import IKeyValStorageGateway
from mugen.core.contract.logging_gateway import ILoggingGateway
from mugen.core.contract.messaging_service import IMessagingService
from mugen.core.contract.mh_extension import IMHExtension
from mugen.core.contract.rag_extension import IRAGExtension
from mugen.core.contract.rpp_extension import IRPPExtension
from mugen.core.contract.user_service import IUserService

CHAT_THREAD_VERSION: int = 1

CHAT_THREADS_LIST_VERSION: int = 1


# pylint: disable=too-many-instance-attributes
class DefaultMessagingService(IMessagingService):
    """The default implementation of IMessagingService."""

    _ct_extensions: list[ICTExtension] = []

    _ctx_extensions: list[ICTXExtension] = []

    _mh_extensions: list[IMHExtension] = []

    _rag_extensions: list[IRAGExtension] = []

    _rpp_extensions: list[IRPPExtension] = []

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

    # pylint: disable=too-many-branches
    # pylint: disable=too-many-statements
    # pylint: disable=too-many-locals
    async def handle_text_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        content: str,
    ) -> str | None:
        if content.strip() == "//clear.":
            # Empty attention thread.
            await self._get_attention_thread_key(room_id, "", True)

            # Clear RAG caches.
            for rag_ext in self._rag_extensions:
                # Filter extensions that don't support the
                # calling platform.
                if not self._platform_supported(platform, rag_ext):
                    continue

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
        completion_context += self._get_system_context(platform, sender)

        # Add chat history to completion context.
        attention_thread["messages"].append({"role": "user", "content": content})
        completion_context += attention_thread["messages"]

        # Execute RAG pipelines and get data if any was found.
        # If the user message did not trigger an RAG queries, the information from
        # previous successful queries will still be cached.
        for rag_ext in self._rag_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not self._platform_supported(platform, rag_ext):
                continue

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
        )

        # If the chat completion attempt failed, set it to "Error" so that the user
        # will be aware of the failure.
        if chat_completion is None:
            self._logging_gateway.debug("chat_completion: None.")
            chat_completion = SimpleNamespace()
            chat_completion.content = "Error"

        assistant_response = chat_completion.content

        # Save current thread first.
        self._save_chat_thread(attention_thread_key, attention_thread)

        # Pass the response to pre-processor extensions.
        for rpp_ext in self._rpp_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not self._platform_supported(platform, rpp_ext):
                continue

            assistant_response, task, end_task = await rpp_ext.preprocess_response(
                assistant_response
            )

            # If no task or end task is detected,
            # we have nothing else to do.
            if not (task or end_task):
                continue

            # We must determine if the response contains
            # a conversational trigger before we attempt
            # to refresh the chat thread.
            trigger_hits = 0
            if end_task:
                for ct_ext in self._ct_extensions:
                    # Filter extensions that don't support the
                    # calling platform.
                    if not self._platform_supported(platform, ct_ext):
                        continue

                    for trigger in ct_ext.triggers:
                        if trigger in assistant_response:
                            trigger_hits += 1

            # Only attempt the refresh if a conversational trigger was not
            # detected.
            if not trigger_hits > 0:
                await self._get_attention_thread_key(room_id, "", True, task)

        if assistant_response == "":
            self._logging_gateway.debug("Empty response.")
            return assistant_response

        # Persist chat history.
        self._logging_gateway.debug("Persist attention thread.")
        attention_thread["messages"].append(
            {
                "role": "assistant",
                "content": assistant_response,
            }
        )
        self._save_chat_thread(attention_thread_key, attention_thread)

        self._logging_gateway.debug(
            "Pass response to triggered services for processing."
        )

        # Pass the response to conversational trigger extensions for post processing.
        tasks = []
        for ct_ext in self._ct_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not self._platform_supported(platform, ct_ext):
                continue

            tasks.append(
                asyncio.create_task(
                    ct_ext.process_message(
                        assistant_response,
                        "assistant",
                        room_id,
                        sender,
                        attention_thread_key,
                    )
                )
            )
        asyncio.gather(*tasks)

        return assistant_response

    @property
    def mh_extensions(self) -> list[IMHExtension]:
        return self._mh_extensions

    def register_ct_extension(self, ext: ICTExtension) -> None:
        self._ct_extensions.append(ext)

    def register_ctx_extension(self, ext: ICTXExtension) -> None:
        self._ctx_extensions.append(ext)

    def register_mh_extension(self, ext: IMHExtension) -> None:
        self._mh_extensions.append(ext)

    def register_rag_extension(self, ext: IRAGExtension) -> None:
        self._rag_extensions.append(ext)

    def register_rpp_extension(self, ext: IRPPExtension) -> None:
        self._rpp_extensions.append(ext)

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

    def _get_system_context(self, platform: str, sender: str) -> list[dict]:
        """Return a list of system messages to add context to user message."""
        context = []

        if "mugen_assistant_persona" in self._config.__dict__.keys():
            # Append assistant persona to context.
            context.append(
                {
                    "role": "system",
                    "content": self._config.mugen_assistant_persona,
                }
            )

        # Append information from CTX extensions to context.
        for ctx_ext in self._ctx_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not self._platform_supported(platform, ctx_ext):
                continue

            context += ctx_ext.get_context(sender)

        # Append information from CT extensions to context.
        for ct_ext in self._ct_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not self._platform_supported(platform, ct_ext):
                continue

            context += ct_ext.get_context(sender)

        return context

    def _platform_supported(self, platform: str, ext) -> bool:
        """Filter extensions that don't support the calling platform."""
        if ext.platforms == []:
            return True

        return platform in ext.platforms

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

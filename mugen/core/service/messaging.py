"""Provides an implementation of IMessagingService."""

__all__ = ["DefaultMessagingService"]

import asyncio
from datetime import datetime
import json
import pickle
from types import SimpleNamespace
import uuid

from dependency_injector import providers

from mugen.core.contract.extension.ct import ICTExtension
from mugen.core.contract.extension.ctx import ICTXExtension
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.extension.rag import IRAGExtension
from mugen.core.contract.extension.rpp import IRPPExtension
from mugen.core.contract.gateway.completion import ICompletionGateway
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.user import IUserService


# pylint: disable=too-many-instance-attributes
class DefaultMessagingService(IMessagingService):
    """The default implementation of IMessagingService."""

    _thread_version: int = 1

    _thread_list_version: int = 1

    _ct_extensions: list[ICTExtension] = []

    _ctx_extensions: list[ICTXExtension] = []

    _mh_extensions: list[IMHExtension] = []

    _rag_extensions: list[IRAGExtension] = []

    _rpp_extensions: list[IRPPExtension] = []

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        config: providers.Configuration,  # pylint: disable=c-extension-no-member
        completion_gateway: ICompletionGateway,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
        user_service: IUserService,
    ) -> None:
        self._config = config
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
        match content.strip():
            case "//clear.":
                # Clear attention thread.
                self.clear_attention_thread(room_id)

                # Clear RAG caches.
                for rag_ext in self._rag_extensions:
                    # Filter extensions that don't support the
                    # calling platform.
                    if not self._platform_supported(platform, rag_ext):
                        continue

                    if self._keyval_storage_gateway.has_key(rag_ext.cache_key):
                        self._keyval_storage_gateway.remove(rag_ext.cache_key)
                return "PUC executed."
            case _:
                pass

        # Load previous history from storage if it exists.
        attention_thread = self.load_attention_thread(room_id)

        # self._logging_gateway.debug(f"attention_thread: {attention_thread}")

        completion_context = []

        # Add system context to completion context.
        completion_context += self._get_system_context(platform, sender)

        # Add user message to attention thread.
        attention_thread["messages"].append({"role": "user", "content": content})

        # Log user message if conversation debugging flag set.
        if self._config.mugen.debug_conversation():
            self._logging_gateway.debug(
                json.dumps(attention_thread["messages"], indent=4)
            )

        # Add thread history to completion context.
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
        # Get assistant response based on conversation history, system context,
        # and RAG data.
        self._logging_gateway.debug("Get completion.")
        completion = await self._completion_gateway.get_completion(
            context=completion_context,
        )

        # If the completion attempt failed, set response to "Error" so that the user
        # will be aware of the failure.
        if completion is None:
            self._logging_gateway.debug("Completion is None.")
            completion = SimpleNamespace()
            completion.content = "Error"

        assistant_response = completion.content

        # Save current thread first.
        self._logging_gateway.debug("Persist attention thread.")
        attention_thread["messages"].append(
            {
                "role": "assistant",
                "content": assistant_response,
            }
        )
        self.save_attention_thread(room_id, attention_thread)

        # Log assistant message if conversation debugging flag set.
        if self._config.mugen.debug_conversation():
            self._logging_gateway.debug(
                json.dumps(attention_thread["messages"], indent=4)
            )

        # Pass the response to pre-processor extensions.
        for rpp_ext in self._rpp_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not self._platform_supported(platform, rpp_ext):
                continue

            assistant_response = await rpp_ext.preprocess_response(
                room_id,
                user_id=sender,
            )

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
                        message=assistant_response,
                        role="assistant",
                        room_id=room_id,
                        user_id=sender,
                    )
                )
            )
        asyncio.gather(*tasks)

        return assistant_response

    def add_message_to_thread(self, message: str, role: str, room_id: str) -> None:
        # Load the attention thread.
        attention_thread = self.load_attention_thread(room_id)

        # Append a new assistant response.
        attention_thread["messages"].append({"role": role, "content": message})

        # Persist the attention thread.
        self.save_attention_thread(room_id, attention_thread)

    def clear_attention_thread(self, room_id: str, keep: int = 0) -> None:
        # Get the attention thread.
        attention_thread = self.load_attention_thread(room_id)

        if keep == 0:
            attention_thread["messages"] = []
        else:
            attention_thread["messages"] = attention_thread["messages"][-abs(keep) :]

        # Persist the cleared thread.
        self.save_attention_thread(room_id, attention_thread)

    def load_attention_thread(self, room_id: str) -> dict | None:
        thread_key = self._get_attention_thread_key(room_id)
        return pickle.loads(self._keyval_storage_gateway.get(thread_key, False))

    def save_attention_thread(self, room_id: str, thread: dict) -> None:
        thread["last_saved"] = datetime.now().strftime("%s")
        thread_key = self._get_attention_thread_key(room_id)
        self._keyval_storage_gateway.put(thread_key, pickle.dumps(thread))

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

    def trigger_in_response(self, response: str, platform: str = None) -> bool:
        hits = 0
        for ct_ext in self._ct_extensions:

            if platform is not None and not self._platform_supported(platform, ct_ext):
                continue

            for trigger in ct_ext.triggers:
                if trigger in response:
                    hits += 1

        return hits > 0

    def _get_attention_thread_key(self, room_id: str) -> str:
        """Get the attention thread that the message is related to."""
        # Get the key to retrieve the list of attention threads for this room.
        thread_list_key = f"chat_threads_list:{room_id}"

        # If thread_list_key does not exist.
        if not self._keyval_storage_gateway.has_key(thread_list_key):
            # This is the first message in this room.
            # Create a new thread list and get the attention thread key.
            self._logging_gateway.debug("New room. Generating new list and new thread.")
            thread_key = self._generate_thread_list(thread_list_key, True)
            return thread_key
        # else:
        # The key does exist.
        thread_list = pickle.loads(
            self._keyval_storage_gateway.get(thread_list_key, False)
        )
        return thread_list["attention_thread"]

    def _generate_thread_list(self, thread_list_key: str, new_list: bool) -> str:
        """Generate a new attention thread key."""
        # Generate new key.
        self._logging_gateway.debug("Generating new attention thread key.")
        thread_key = f"chat_thread:{uuid.uuid1()}"

        thread_list = {}
        # If its a new thread list.
        if new_list:
            # Create a new thread list, and make the new thread the attention thread.
            self._logging_gateway.debug("Creating new thread list.")
            thread_list["version"] = self._thread_list_version
            thread_list["attention_thread"] = thread_key
            thread_list["threads"] = [thread_key]
        else:
            # The thread list exists.
            self._logging_gateway.debug("Load existing thread list.")
            thread_list = pickle.loads(
                self._keyval_storage_gateway.get(thread_list_key, False)
            )

            # Set new key as attention thread and append it to the threads list.
            thread_list["attention_thread"] = thread_key
            thread_list["threads"].append(thread_key)

        # Persist thread list.
        self._keyval_storage_gateway.put(thread_list_key, pickle.dumps(thread_list))

        # Default values for attention thread.
        attention_thread = {
            "created": datetime.now().strftime("%s"),
            "last_saved": datetime.now().strftime("%s"),
            "messages": [],
            "version": self._thread_version,
        }
        self._keyval_storage_gateway.put(thread_key, pickle.dumps(attention_thread))

        return thread_key

    def _get_system_context(self, platform: str, sender: str) -> list[dict]:
        """Return a list of system messages to add context to user message."""
        context = []

        # Append assistant persona to context.
        context.append(
            {
                "role": "system",
                "content": self._config.mugen.assistant.persona(),
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

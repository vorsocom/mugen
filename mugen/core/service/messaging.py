"""Provides an implementation of IMessagingService."""

__all__ = ["DefaultMessagingService"]

import asyncio
import json
import pickle
from types import SimpleNamespace

from mugen.core.contract.extension.cp import ICPExtension
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

    _cp_extensions: list[ICPExtension] = []

    _ct_extensions: list[ICTExtension] = []

    _ctx_extensions: list[ICTXExtension] = []

    _mh_extensions: list[IMHExtension] = []

    _rag_extensions: list[IRAGExtension] = []

    _rpp_extensions: list[IRPPExtension] = []

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        config: SimpleNamespace,
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
        # Handle commands.
        command_responses: list[str] = []
        for cp_ext in self._cp_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not cp_ext.platform_supported(platform):
                continue

            command_response = await cp_ext.process_message(
                content,
                room_id,
                sender,
            )

            if command_response is not None:
                command_responses.append(command_response)

        if len(command_responses) > 0:
            return " ".join(command_responses)

        # Load previous history from storage if it exists.
        chat_history = self.load_chat_history(room_id)

        # self._logging_gateway.debug(f"attention_thread: {attention_thread}")

        completion_context = []

        # Add system context to completion context.
        for ctx_ext in self._ctx_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not ctx_ext.platform_supported(platform):
                continue

            completion_context += ctx_ext.get_context(sender)

        # Add user message to attention thread.
        chat_history["messages"].append({"role": "user", "content": content})

        # Log user message if conversation debugging flag set.
        if self._config.mugen.debug_conversation:
            self._logging_gateway.debug(json.dumps(chat_history["messages"], indent=4))

        # Add thread history to completion context.
        completion_context += chat_history["messages"]

        # Execute RAG pipelines and get data if any was found.
        # If the user message did not trigger an RAG queries, the information from
        # previous successful queries will still be cached.
        for rag_ext in self._rag_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not rag_ext.platform_supported(platform):
                continue

            await rag_ext.retrieve(sender, content, chat_history)
            cache_key = f"{rag_ext.cache_key}__{sender}"
            if self._keyval_storage_gateway.has_key(cache_key):
                rp_cache = pickle.loads(
                    self._keyval_storage_gateway.get(
                        cache_key,
                        False,
                    )
                )
                augmentation = (
                    "[CONTEXT]\n"
                    f'{"\n\n".join([f'{i+1}. {x["content"]}' for i, x in enumerate(rp_cache)])}\n'
                    "[/CONTEXT]\n\n"
                    "[USER_MESSAGE]\n"
                    f'{completion_context[-1]["content"]}\n'
                    "[/USER_MESSAGE]"
                )
                completion_context[-1]["content"] = augmentation
                self._keyval_storage_gateway.remove(cache_key)

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
        chat_history["messages"].append(
            {
                "role": "assistant",
                "content": assistant_response,
            }
        )
        self.save_chat_history(room_id, chat_history)

        # Log assistant message if conversation debugging flag set.
        if self._config.mugen.debug_conversation:
            self._logging_gateway.debug(json.dumps(chat_history["messages"], indent=4))

        # Pass the response to pre-processor extensions.
        for rpp_ext in self._rpp_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not rpp_ext.platform_supported(platform):
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
            if not ct_ext.platform_supported(platform):
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

    def add_message_to_history(self, message: str, role: str, room_id: str) -> None:
        # Load the attention thread.
        history = self.load_chat_history(room_id)

        # Append a new assistant response.
        history["messages"].append({"role": role, "content": message})

        # Persist the attention thread.
        self.save_chat_history(room_id, history)

    def clear_chat_history(self, room_id: str, keep: int = 0) -> None:
        # Get the attention thread.
        history = self.load_chat_history(room_id)

        if keep == 0:
            history["messages"] = []
        else:
            history["messages"] = history["messages"][-abs(keep) :]

        # Persist the cleared thread.
        self.save_chat_history(room_id, history)

    def load_chat_history(self, room_id: str) -> dict | None:
        history_key = f"chat_history:{room_id}"
        if self._keyval_storage_gateway.has_key(history_key):
            return pickle.loads(self._keyval_storage_gateway.get(history_key, False))

        return {"messages": []}

    def save_chat_history(self, room_id: str, history: dict) -> None:
        history_key = f"chat_history:{room_id}"
        self._keyval_storage_gateway.put(history_key, pickle.dumps(history))

    @property
    def mh_extensions(self) -> list[IMHExtension]:
        return self._mh_extensions

    def register_cp_extension(self, ext: ICPExtension) -> None:
        self._cp_extensions.append(ext)

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

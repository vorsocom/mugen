"""Provides an implementation of IMHExtension for text messages across all platforms."""

__all__ = ["DefaultTextMHExtension"]

import asyncio
import json
import pickle
from types import SimpleNamespace
from typing import Any

from mugen.core import di
from mugen.core.contract.gateway.completion import ICompletionGateway
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.messaging import IMessagingService


class DefaultTextMHExtension(IMHExtension):
    """An implmentation of IMHExtension for text messages across all platforms."""

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def __init__(
        self,
        completion_gateway: ICompletionGateway = di.container.completion_gateway,
        config: SimpleNamespace = di.container.config,
        keyval_storage_gateway: IKeyValStorageGateway = di.container.keyval_storage_gateway,
        logging_gateway: ILoggingGateway = di.container.logging_gateway,
        messaging_service: IMessagingService = di.container.messaging_service,
    ) -> None:
        self._completion_gateway = completion_gateway
        self._config = config
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._messaging_service = messaging_service

    @property
    def message_types(self) -> list[str]:
        return ["text"]

    @property
    def platforms(self) -> list[str]:
        return []

    # pylint: disable=too-many-locals
    # pylint: disable=too-many-branches
    # pylint: disable=too-many-statements
    async def handle_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: Any,
        message_context: list[dict] = None,
    ) -> list[dict] | None:
        # Responses from extensions, for the user,
        # will be aggregated using this var.
        extension_responses: list[dict] = []

        # Handle commands.
        for cp_ext in self._messaging_service.cp_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not cp_ext.platform_supported(platform):
                continue

            if message.strip() not in cp_ext.commands:
                continue

            command_response = await cp_ext.process_message(
                message,
                room_id,
                sender,
            )

            if command_response is not None:
                extension_responses += command_response

        # If extension_responses is not empty it means commands
        # were executed and we should exit.
        if extension_responses:
            return extension_responses

        # Load previous history from storage if it exists.
        chat_history = self._load_chat_history(room_id)

        # self._logging_gateway.debug(f"attention_thread: {attention_thread}")

        completion_context = []

        # Add system context to completion context.
        for ctx_ext in self._messaging_service.ctx_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not ctx_ext.platform_supported(platform):
                continue

            completion_context += ctx_ext.get_context(sender)

        # Add user message to attention thread.
        chat_history["messages"].append({"role": "user", "content": message})

        # Log user message if conversation debugging flag set.
        if self._config.mugen.debug_conversation:
            self._logging_gateway.debug(json.dumps(chat_history["messages"], indent=4))

        # Add thread history to completion context.
        completion_context += chat_history["messages"]

        # Execute RAG pipelines and get data if any was found.
        rag_data: list[dict] = []
        for rag_ext in self._messaging_service.rag_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not rag_ext.platform_supported(platform):
                continue

            rag_context, rag_responses = await rag_ext.retrieve(
                sender,
                message,
                chat_history,
            )

            rag_data += rag_context
            extension_responses += rag_responses

        # Augment user message with message context and RAG data
        # if available.
        augmentation_data: list[dict] = []
        if message_context:
            augmentation_data += message_context

        if rag_data:
            augmentation_data += rag_data

        if augmentation_data:
            context_list = [
                f'{i+1}. {x["content"]}' for i, x in enumerate(augmentation_data)
            ]

            augmentated_message = (
                "[CONTEXT]\n"
                f'{"\n\n".join(context_list)}\n'
                "[/CONTEXT]\n\n"
                "[USER_MESSAGE]\n"
                f'{completion_context[-1]["content"]}\n'
                "[/USER_MESSAGE]"
            )
            completion_context[-1]["content"] = augmentated_message

        # Get assistant response based on conversation history, system context,
        # and augmented data.
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
        self._save_chat_history(room_id, chat_history)

        # Log assistant message if conversation debugging flag set.
        if self._config.mugen.debug_conversation:
            self._logging_gateway.debug(json.dumps(chat_history["messages"], indent=4))

        # Pass the response to pre-processor extensions.
        for rpp_ext in self._messaging_service.rpp_extensions:
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
        for ct_ext in self._messaging_service.ct_extensions:
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

        return [{"type": "text", "content": assistant_response}] + extension_responses

    def _load_chat_history(self, room_id: str) -> dict | None:
        history_key = f"chat_history:{room_id}"
        if self._keyval_storage_gateway.has_key(history_key):
            return pickle.loads(self._keyval_storage_gateway.get(history_key, False))

        return {"messages": []}

    def _save_chat_history(self, room_id: str, history: dict) -> None:
        history_key = f"chat_history:{room_id}"
        self._keyval_storage_gateway.put(history_key, pickle.dumps(history))

"""Provides an implementation of ICPExtension to clear chat history."""

__all__ = ["ClearChatHistoryICPExtension"]

import json
from types import SimpleNamespace


from mugen.core.contract.extension.cp import ICPExtension
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core import di


def _config_provider():
    return di.container.config


def _keyval_storage_gateway_provider():
    return di.container.keyval_storage_gateway


class ClearChatHistoryICPExtension(ICPExtension):
    """An implementation of ICPExtension to clear chat history."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        config: SimpleNamespace | None = None,
        keyval_storage_gateway: IKeyValStorageGateway | None = None,
    ) -> None:
        self._config = config if config is not None else _config_provider()
        self._keyval_storage_gateway = (
            keyval_storage_gateway
            if keyval_storage_gateway is not None
            else _keyval_storage_gateway_provider()
        )

    @property
    def platforms(self) -> list[str]:
        return []

    @property
    def commands(self) -> list[str]:
        return [self._config.mugen.commands.clear]

    async def process_message(  # pylint: disable=too-many-arguments
        self,
        message: str,
        room_id: str,
        user_id: str,
    ) -> list[dict] | None:
        return self._handle_clear_command(room_id)

    def _handle_clear_command(
        self,
        room_id: str,
    ) -> list[dict]:
        # Clear chat history.
        self._clear_chat_history(room_id)
        return [
            {
                "type": "text",
                "content": "Context cleared.",
            },
        ]

    def _clear_chat_history(self, room_id: str, keep: int = 0) -> None:
        # Get the attention thread.
        history = self._load_chat_history(room_id)

        if keep == 0:
            history["messages"] = []
        else:
            history["messages"] = history["messages"][-abs(keep) :]

        # Persist the cleared thread.
        self._save_chat_history(room_id, history)

    def _load_chat_history(self, room_id: str) -> dict | None:
        history_key = f"chat_history:{room_id}"
        if self._keyval_storage_gateway.has_key(history_key):
            payload = self._keyval_storage_gateway.get(history_key, False)
            if isinstance(payload, bytes):
                try:
                    payload = payload.decode("utf-8")
                except UnicodeDecodeError:
                    return {"messages": []}
            try:
                loaded = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                return {"messages": []}
            if isinstance(loaded, dict) and isinstance(loaded.get("messages"), list):
                return loaded
            return {"messages": []}

        return {"messages": []}

    def _save_chat_history(self, room_id: str, history: dict) -> None:
        history_key = f"chat_history:{room_id}"
        self._keyval_storage_gateway.put(history_key, json.dumps(history))

"""Provides an implementation of ICPExtension to clear chat history."""

__all__ = ["ClearChatHistoryICPExtension"]

from types import SimpleNamespace


from mugen.core.contract.extension.cp import ICPExtension
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.gateway.storage.keyval_model import KeyValConflictError
from mugen.core import di


def _config_provider():
    return di.container.config


def _keyval_storage_gateway_provider():
    return di.container.keyval_storage_gateway


class ClearChatHistoryICPExtension(ICPExtension):
    """An implementation of ICPExtension to clear chat history."""

    _default_history_save_cas_retries: int = 5

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
        self._history_save_cas_retries = self._resolve_history_save_cas_retries()

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
        return await self._handle_clear_command(room_id)

    async def _handle_clear_command(
        self,
        room_id: str,
    ) -> list[dict]:
        # Clear chat history.
        await self._clear_chat_history(room_id)
        return [
            {
                "type": "text",
                "content": "Context cleared.",
            },
        ]

    async def _clear_chat_history(self, room_id: str, keep: int = 0) -> None:
        # Get the attention thread.
        history = await self._load_chat_history(room_id)

        if keep == 0:
            history["messages"] = []
        else:
            history["messages"] = history["messages"][-abs(keep) :]

        # Persist the cleared thread.
        await self._save_chat_history(room_id, history)

    async def _load_chat_history(self, room_id: str) -> dict | None:
        history_key = f"chat_history:{room_id}"
        loaded = await self._keyval_storage_gateway.get_json(history_key)
        if isinstance(loaded, dict) and isinstance(loaded.get("messages"), list):
            return loaded

        return {"messages": []}

    async def _save_chat_history(self, room_id: str, history: dict) -> None:
        history_key = f"chat_history:{room_id}"
        for _ in range(self._history_save_cas_retries):
            entry = await self._keyval_storage_gateway.get_entry(history_key)
            expected_row_version = 0
            if entry is not None:
                expected_row_version = int(entry.row_version)
            try:
                await self._keyval_storage_gateway.put_json(
                    history_key,
                    history,
                    expected_row_version=expected_row_version,
                )
                return
            except KeyValConflictError:
                continue

        await self._keyval_storage_gateway.put_json(history_key, history)

    def _resolve_history_save_cas_retries(self) -> int:
        raw_value = getattr(
            getattr(getattr(self._config, "mugen", SimpleNamespace()), "messaging", None),
            "history_save_cas_retries",
            self._default_history_save_cas_retries,
        )
        if isinstance(raw_value, int) and not isinstance(raw_value, bool):
            if raw_value > 0:
                return raw_value
        return self._default_history_save_cas_retries

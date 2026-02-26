"""Unit tests for mugen.core.plugin.command.clear_history.cp_ext."""

import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from mugen.core.contract.gateway.storage.keyval_model import KeyValConflictError
from mugen.core.plugin.command.clear_history.cp_ext import ClearChatHistoryICPExtension


class _MemoryKeyVal:
    def __init__(self):
        self.store = {}
        self._versions: dict[str, int] = {}

    def has_key(self, key: str) -> bool:
        return key in self.store

    def get(self, key: str, _decode: bool = True):
        return self.store[key]

    def put(self, key: str, value):
        self.store[key] = value
        self._versions[key] = int(self._versions.get(key, 0)) + 1

    async def get_json(self, key: str):
        payload = self.store.get(key)
        if payload in [None, ""]:
            return None
        if isinstance(payload, bytes):
            try:
                payload = payload.decode("utf-8")
            except UnicodeDecodeError:
                return None
        try:
            loaded = json.loads(payload)
        except (TypeError, ValueError):
            return None
        return loaded

    async def get_entry(self, key: str):
        if key not in self.store:
            return None
        return SimpleNamespace(
            row_version=int(self._versions.get(key, 1)),
        )

    async def put_json(
        self,
        key: str,
        value,
        *,
        expected_row_version: int | None = None,
    ) -> None:
        current_row_version = 0 if key not in self.store else int(
            self._versions.get(key, 1)
        )
        if (
            expected_row_version is not None
            and int(expected_row_version) != current_row_version
        ):
            raise KeyValConflictError(
                namespace="default",
                key=key,
                expected_row_version=int(expected_row_version),
                current_row_version=current_row_version,
            )

        self.store[key] = json.dumps(value, ensure_ascii=True)
        self._versions[key] = 1 if current_row_version == 0 else current_row_version + 1


def _make_config(command: str = "/clear") -> SimpleNamespace:
    return SimpleNamespace(
        mugen=SimpleNamespace(commands=SimpleNamespace(clear=command))
    )


class TestMugenClearHistoryCpExt(unittest.IsolatedAsyncioTestCase):
    """Covers command handling and persistence behavior."""

    def _new_ext(self, *, command: str = "/clear", keyval=None):
        return ClearChatHistoryICPExtension(
            config=_make_config(command=command),
            keyval_storage_gateway=keyval or _MemoryKeyVal(),
        )

    async def test_properties_and_process_message(self) -> None:
        keyval = _MemoryKeyVal()
        keyval.put(
            "chat_history:room-1",
            json.dumps({"messages": [{"role": "user", "content": "hello"}]}),
        )
        ext = self._new_ext(keyval=keyval, command="/wipe")

        self.assertEqual(ext.platforms, [])
        self.assertEqual(ext.commands, ["/wipe"])

        result = await ext.process_message(
            message="/wipe",
            room_id="room-1",
            user_id="user-1",
        )

        self.assertEqual(result, [{"type": "text", "content": "Context cleared."}])
        saved = json.loads(keyval.store["chat_history:room-1"])
        self.assertEqual(saved["messages"], [])

    async def test_load_and_save_history_roundtrip(self) -> None:
        keyval = _MemoryKeyVal()
        ext = self._new_ext(keyval=keyval)

        self.assertEqual(
            await ext._load_chat_history("room-2"), {"messages": []}
        )  # pylint: disable=protected-access

        history = {
            "messages": [
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
            ]
        }
        await ext._save_chat_history("room-2", history)  # pylint: disable=protected-access
        loaded = await ext._load_chat_history("room-2")  # pylint: disable=protected-access
        self.assertEqual(loaded, history)

        keyval.store["chat_history:room-2"] = "{"
        self.assertEqual(
            await ext._load_chat_history("room-2"),
            {"messages": []},
        )

        keyval.store["chat_history:room-2"] = b"\xff"
        self.assertEqual(
            await ext._load_chat_history("room-2"),
            {"messages": []},
        )

        keyval.store["chat_history:room-2"] = json.dumps(["not-a-dict"])
        self.assertEqual(
            await ext._load_chat_history("room-2"),
            {"messages": []},
        )

    async def test_clear_chat_history_keep_modes(self) -> None:
        keyval = _MemoryKeyVal()
        ext = self._new_ext(keyval=keyval)
        history = {
            "messages": [
                {"role": "user", "content": "m1"},
                {"role": "assistant", "content": "m2"},
                {"role": "user", "content": "m3"},
            ]
        }

        await ext._save_chat_history("room-3", history)  # pylint: disable=protected-access
        await ext._clear_chat_history("room-3", keep=2)  # pylint: disable=protected-access
        self.assertEqual(
            (await ext._load_chat_history("room-3"))[
                "messages"
            ],  # pylint: disable=protected-access
            [
                {"role": "assistant", "content": "m2"},
                {"role": "user", "content": "m3"},
            ],
        )

        await ext._save_chat_history("room-3", history)  # pylint: disable=protected-access
        await ext._clear_chat_history("room-3", keep=-1)  # pylint: disable=protected-access
        self.assertEqual(
            (await ext._load_chat_history("room-3"))[
                "messages"
            ],  # pylint: disable=protected-access
            [{"role": "user", "content": "m3"}],
        )

        await ext._save_chat_history("room-3", history)  # pylint: disable=protected-access
        await ext._clear_chat_history("room-3", keep=0)  # pylint: disable=protected-access
        self.assertEqual(
            (await ext._load_chat_history("room-3"))[
                "messages"
            ],  # pylint: disable=protected-access
            [],
        )

    async def test_save_chat_history_conflict_fallback_and_retry_config_default(self) -> None:
        keyval = Mock()
        keyval.get_entry = AsyncMock(return_value=SimpleNamespace(row_version=1))
        keyval.put_json = AsyncMock(
            side_effect=[
                KeyValConflictError(
                    namespace="default",
                    key="chat_history:room-x",
                    expected_row_version=1,
                    current_row_version=2,
                ),
                KeyValConflictError(
                    namespace="default",
                    key="chat_history:room-x",
                    expected_row_version=1,
                    current_row_version=2,
                ),
                KeyValConflictError(
                    namespace="default",
                    key="chat_history:room-x",
                    expected_row_version=1,
                    current_row_version=2,
                ),
                KeyValConflictError(
                    namespace="default",
                    key="chat_history:room-x",
                    expected_row_version=1,
                    current_row_version=2,
                ),
                KeyValConflictError(
                    namespace="default",
                    key="chat_history:room-x",
                    expected_row_version=1,
                    current_row_version=2,
                ),
                None,
            ]
        )
        ext = ClearChatHistoryICPExtension(
            config=SimpleNamespace(
                mugen=SimpleNamespace(
                    commands=SimpleNamespace(clear="/clear"),
                    messaging=SimpleNamespace(history_save_cas_retries=0),
                )
            ),
            keyval_storage_gateway=keyval,
        )

        self.assertEqual(
            ext._history_save_cas_retries,  # pylint: disable=protected-access
            ext._default_history_save_cas_retries,  # pylint: disable=protected-access
        )

        await ext._save_chat_history(  # pylint: disable=protected-access
            "room-x",
            {"messages": []},
        )
        self.assertEqual(keyval.put_json.await_count, 6)

    async def test_retry_config_non_integer_uses_default(self) -> None:
        ext = ClearChatHistoryICPExtension(
            config=SimpleNamespace(
                mugen=SimpleNamespace(
                    commands=SimpleNamespace(clear="/clear"),
                    messaging=SimpleNamespace(history_save_cas_retries="bad"),
                )
            ),
            keyval_storage_gateway=_MemoryKeyVal(),
        )
        self.assertEqual(
            ext._history_save_cas_retries,  # pylint: disable=protected-access
            ext._default_history_save_cas_retries,  # pylint: disable=protected-access
        )

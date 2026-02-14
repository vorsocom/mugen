"""Unit tests for mugen.core.plugin.command.clear_history.cp_ext."""

import pickle
from types import SimpleNamespace
import unittest

from mugen.core.plugin.command.clear_history.cp_ext import ClearChatHistoryICPExtension


class _MemoryKeyVal:
    def __init__(self):
        self.store = {}

    def has_key(self, key: str) -> bool:
        return key in self.store

    def get(self, key: str, _decode: bool = True):
        return self.store[key]

    def put(self, key: str, value):
        self.store[key] = value


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
            pickle.dumps({"messages": [{"role": "user", "content": "hello"}]}),
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
        saved = pickle.loads(keyval.store["chat_history:room-1"])
        self.assertEqual(saved["messages"], [])

    async def test_load_and_save_history_roundtrip(self) -> None:
        keyval = _MemoryKeyVal()
        ext = self._new_ext(keyval=keyval)

        self.assertEqual(
            ext._load_chat_history("room-2"), {"messages": []}
        )  # pylint: disable=protected-access

        history = {
            "messages": [
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
            ]
        }
        ext._save_chat_history("room-2", history)  # pylint: disable=protected-access
        loaded = ext._load_chat_history("room-2")  # pylint: disable=protected-access
        self.assertEqual(loaded, history)

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

        ext._save_chat_history("room-3", history)  # pylint: disable=protected-access
        ext._clear_chat_history("room-3", keep=2)  # pylint: disable=protected-access
        self.assertEqual(
            ext._load_chat_history("room-3")[
                "messages"
            ],  # pylint: disable=protected-access
            [
                {"role": "assistant", "content": "m2"},
                {"role": "user", "content": "m3"},
            ],
        )

        ext._save_chat_history("room-3", history)  # pylint: disable=protected-access
        ext._clear_chat_history("room-3", keep=-1)  # pylint: disable=protected-access
        self.assertEqual(
            ext._load_chat_history("room-3")[
                "messages"
            ],  # pylint: disable=protected-access
            [{"role": "user", "content": "m3"}],
        )

        ext._save_chat_history("room-3", history)  # pylint: disable=protected-access
        ext._clear_chat_history("room-3", keep=0)  # pylint: disable=protected-access
        self.assertEqual(
            ext._load_chat_history("room-3")[
                "messages"
            ],  # pylint: disable=protected-access
            [],
        )

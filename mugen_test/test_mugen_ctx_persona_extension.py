"""Unit tests for mugen.core.extension.ctx.system_persona."""

from types import SimpleNamespace
import unittest

from mugen.core.extension.ctx.system_persona import SystemPersonaCTXExtension


class TestMugenCtxPersonaExtension(unittest.TestCase):
    """Covers platform metadata and persona context extraction."""

    def test_platforms_returns_empty_list(self) -> None:
        ext = SystemPersonaCTXExtension(config=SimpleNamespace(mugen=SimpleNamespace()))
        self.assertEqual(ext.platforms, [])

    def test_get_context_returns_empty_without_assistant_block(self) -> None:
        ext = SystemPersonaCTXExtension(config=SimpleNamespace(mugen=SimpleNamespace()))
        self.assertEqual(ext.get_context("user-1"), [])

    def test_get_context_returns_empty_without_persona(self) -> None:
        ext = SystemPersonaCTXExtension(
            config=SimpleNamespace(
                mugen=SimpleNamespace(assistant=SimpleNamespace()),
            )
        )
        self.assertEqual(ext.get_context("user-1"), [])

    def test_get_context_returns_empty_when_persona_is_empty(self) -> None:
        ext = SystemPersonaCTXExtension(
            config=SimpleNamespace(
                mugen=SimpleNamespace(
                    assistant=SimpleNamespace(persona=""),
                )
            )
        )
        self.assertEqual(ext.get_context("user-1"), [])

    def test_get_context_includes_system_persona(self) -> None:
        ext = SystemPersonaCTXExtension(
            config=SimpleNamespace(
                mugen=SimpleNamespace(
                    assistant=SimpleNamespace(persona="Be concise."),
                )
            )
        )
        self.assertEqual(
            ext.get_context("user-1"),
            [{"role": "system", "content": "Be concise."}],
        )

"""Unit tests for mugen.core.contract.extension.IExtensionBase."""

import unittest

from mugen.core.contract.extension import IExtensionBase


class _TestExtension(IExtensionBase):
    def __init__(self, platforms: list[str]):
        self._platforms = platforms

    @property
    def platforms(self) -> list[str]:
        return self._platforms


class TestMugenContractExtensionBase(unittest.TestCase):
    """Covers default `platform_supported` behavior on extension base."""

    def test_platform_supported_true_and_false_paths(self) -> None:
        all_platforms = _TestExtension([])
        self.assertTrue(all_platforms.platform_supported("whatsapp"))

        selective = _TestExtension(["matrix"])
        self.assertTrue(selective.platform_supported("matrix"))
        self.assertFalse(selective.platform_supported("whatsapp"))

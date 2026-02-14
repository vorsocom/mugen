"""Unit tests for mugen.core.service.platform.DefaultPlatformService."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from mugen.core.service.platform import DefaultPlatformService


class TestMugenPlatformService(unittest.TestCase):
    """Tests active platform resolution and extension support checks."""

    def test_active_platforms_and_extension_supported(self) -> None:
        config = SimpleNamespace(
            mugen=SimpleNamespace(platforms=["matrix", "telnet"])
        )
        service = DefaultPlatformService(config=config, logging_gateway=Mock())

        self.assertEqual(service.active_platforms, ["matrix", "telnet"])
        self.assertTrue(service.extension_supported(SimpleNamespace(platforms=[])))
        self.assertTrue(service.extension_supported(SimpleNamespace(platforms=["matrix"])))
        self.assertFalse(service.extension_supported(SimpleNamespace(platforms=["whatsapp"])))

"""Unit tests for mugen.core.plugin.telegram.botapi.contrib."""

import unittest
from unittest.mock import Mock

from mugen.core.plugin.telegram.botapi.contrib import contribute


class TestMugenTelegramContrib(unittest.TestCase):
    """Validate Telegram plugin ACP table contributions."""

    def test_contribute_registers_expected_table_specs(self) -> None:
        registry = Mock()

        contribute(
            registry,
            admin_namespace="com.vorsocomputing.mugen.acp",
            plugin_namespace="com.vorsocomputing.mugen.telegram",
        )

        registry.register_table_spec.assert_not_called()

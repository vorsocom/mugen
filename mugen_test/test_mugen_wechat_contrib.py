"""Unit tests for mugen.core.plugin.wechat.contrib."""

import unittest
from unittest.mock import Mock

from mugen.core.plugin.wechat.contrib import contribute


class TestMugenWeChatContrib(unittest.TestCase):
    """Validate WeChat plugin ACP table contributions."""

    def test_contribute_registers_expected_table_specs(self) -> None:
        registry = Mock()

        contribute(
            registry,
            admin_namespace="com.vorsocomputing.mugen.acp",
            plugin_namespace="com.vorsocomputing.mugen.wechat",
        )

        registry.register_table_spec.assert_not_called()

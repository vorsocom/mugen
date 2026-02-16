"""Unit tests for mugen.core.plugin.web.contrib."""

import unittest
from unittest.mock import Mock

from mugen.core.plugin.web.contrib import contribute


class TestMuGenWebContrib(unittest.TestCase):
    """Test no-op ACP contribution for the web framework plugin."""

    def test_contribute_is_noop(self) -> None:
        registry = Mock()

        contribute(
            registry,
            admin_namespace="com.vorsocomputing.mugen.acp",
            plugin_namespace="com.vorsocomputing.mugen.web",
        )

        self.assertEqual(registry.mock_calls, [])

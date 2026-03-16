"""Unit tests for mugen.core.plugin.signal.restapi.contrib."""

import unittest
from unittest.mock import Mock

from mugen.core.plugin.signal.restapi.contrib import contribute


class TestMugenSignalRestapiContrib(unittest.TestCase):
    """Validate Signal plugin ACP table contributions."""

    def test_contribute_registers_expected_table_specs(self) -> None:
        registry = Mock()

        contribute(
            registry,
            admin_namespace="com.vorsocomputing.mugen.acp",
            plugin_namespace="com.vorsocomputing.mugen.signal",
        )

        registry.register_table_spec.assert_not_called()

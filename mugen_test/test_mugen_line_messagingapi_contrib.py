"""Unit tests for mugen.core.plugin.line.messagingapi.contrib."""

import unittest
from unittest.mock import Mock

from mugen.core.plugin.line.messagingapi.contrib import contribute


class TestMugenLineMessagingapiContrib(unittest.TestCase):
    """Validate LINE plugin ACP table contributions."""

    def test_contribute_registers_expected_table_specs(self) -> None:
        registry = Mock()

        contribute(
            registry,
            admin_namespace="com.vorsocomputing.mugen.acp",
            plugin_namespace="com.vorsocomputing.mugen.line",
        )

        table_specs = [
            call.args[0]
            for call in registry.register_table_spec.call_args_list
        ]
        table_names = {spec.table_name for spec in table_specs}
        table_providers = {spec.table_provider for spec in table_specs}

        self.assertEqual(
            table_names,
            {
                "line_messagingapi_event_dedup",
                "line_messagingapi_event_dead_letter",
            },
        )
        self.assertEqual(
            table_providers,
            {
                "mugen.core.plugin.line.messagingapi.model.event_dedup:"
                "LineMessagingAPIEventDedup",
                "mugen.core.plugin.line.messagingapi.model.event_dead_letter:"
                "LineMessagingAPIEventDeadLetter",
            },
        )

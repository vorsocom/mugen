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

        table_specs = [
            call.args[0]
            for call in registry.register_table_spec.call_args_list
        ]
        table_names = {spec.table_name for spec in table_specs}
        table_providers = {spec.table_provider for spec in table_specs}

        self.assertEqual(
            table_names,
            {
                "signal_restapi_event_dedup",
                "signal_restapi_event_dead_letter",
            },
        )
        self.assertEqual(
            table_providers,
            {
                "mugen.core.plugin.signal.restapi.model.event_dedup:"
                "SignalRestAPIEventDedup",
                "mugen.core.plugin.signal.restapi.model.event_dead_letter:"
                "SignalRestAPIEventDeadLetter",
            },
        )

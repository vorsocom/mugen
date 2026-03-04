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

        table_specs = [
            call.args[0]
            for call in registry.register_table_spec.call_args_list
        ]
        table_names = {spec.table_name for spec in table_specs}
        table_providers = {spec.table_provider for spec in table_specs}

        self.assertEqual(
            table_names,
            {
                "telegram_botapi_event_dedup",
                "telegram_botapi_event_dead_letter",
            },
        )
        self.assertEqual(
            table_providers,
            {
                "mugen.core.plugin.telegram.botapi.model.event_dedup:"
                "TelegramBotAPIEventDedup",
                "mugen.core.plugin.telegram.botapi.model.event_dead_letter:"
                "TelegramBotAPIEventDeadLetter",
            },
        )

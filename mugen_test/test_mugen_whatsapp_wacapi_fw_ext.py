"""Unit tests for mugen.core.plugin.whatsapp.wacapi.fw_ext."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import call, Mock, patch

from mugen.core.plugin.whatsapp.wacapi import fw_ext
from mugen.core.plugin.whatsapp.wacapi.flow_data import WhatsAppFlowDataRegistry
from mugen.core.plugin.whatsapp.wacapi.webhook_change import (
    WhatsAppWebhookChangeRegistry,
)


class TestMugenWhatsAppWacapiFWExtension(unittest.IsolatedAsyncioTestCase):
    """Covers WACAPI FW extension provider and setup behavior."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(config="cfg", relational_storage_gateway="rsg")
        with patch.object(fw_ext.di, "container", new=container):
            self.assertEqual(fw_ext._config_provider(), "cfg")
            self.assertEqual(fw_ext._rsg_provider(), "rsg")

    async def test_setup_registers_flow_data_registry_when_missing(self) -> None:
        container = SimpleNamespace(
            config=SimpleNamespace(),
            relational_storage_gateway="rsg",
            has_ext_service=Mock(return_value=False),
            register_ext_service=Mock(),
        )

        with patch.object(fw_ext.di, "container", new=container):
            ext = fw_ext.WACAPIFWExtension()
            self.assertEqual(ext.platforms, ["whatsapp"])
            await ext.setup(app=Mock())

        self.assertEqual(
            container.has_ext_service.call_args_list,
            [
                call(fw_ext.di.EXT_SERVICE_WHATSAPP_FLOW_DATA_REGISTRY),
                call(fw_ext.di.EXT_SERVICE_WHATSAPP_WEBHOOK_CHANGE_REGISTRY),
            ],
        )
        self.assertEqual(container.register_ext_service.call_count, 2)
        service_name, registry = container.register_ext_service.call_args_list[0].args
        self.assertEqual(
            service_name,
            fw_ext.di.EXT_SERVICE_WHATSAPP_FLOW_DATA_REGISTRY,
        )
        self.assertIsInstance(registry, WhatsAppFlowDataRegistry)
        service_name, registry = container.register_ext_service.call_args_list[1].args
        self.assertEqual(
            service_name,
            fw_ext.di.EXT_SERVICE_WHATSAPP_WEBHOOK_CHANGE_REGISTRY,
        )
        self.assertIsInstance(registry, WhatsAppWebhookChangeRegistry)

    async def test_setup_preserves_existing_flow_data_registry(self) -> None:
        container = SimpleNamespace(
            config=SimpleNamespace(),
            relational_storage_gateway="rsg",
            has_ext_service=Mock(return_value=True),
            register_ext_service=Mock(),
        )

        with patch.object(fw_ext.di, "container", new=container):
            ext = fw_ext.WACAPIFWExtension()
            await ext.setup(app=Mock())

        container.register_ext_service.assert_not_called()


if __name__ == "__main__":
    unittest.main()

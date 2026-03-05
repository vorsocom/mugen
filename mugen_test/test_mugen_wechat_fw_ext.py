"""Unit tests for mugen.core.plugin.wechat.fw_ext."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from quart import Quart

from mugen.core.plugin.wechat import fw_ext


class TestMugenWeChatFWExt(unittest.IsolatedAsyncioTestCase):
    """Covers WeChat FW extension provider wiring and setup path."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(
            config="cfg",
            relational_storage_gateway="rsg",
        )
        with patch.object(fw_ext.di, "container", new=container):
            self.assertEqual(fw_ext._config_provider(), "cfg")
            self.assertEqual(fw_ext._rsg_provider(), "rsg")

    async def test_setup_imports_webhook_module(self) -> None:
        ext = fw_ext.WeChatFWExtension(
            config_provider=lambda: SimpleNamespace(),
            rsg_provider=lambda: object(),
        )
        self.assertEqual(ext.platforms, ["wechat"])

        app = Quart("test_app")
        await ext.setup(app)


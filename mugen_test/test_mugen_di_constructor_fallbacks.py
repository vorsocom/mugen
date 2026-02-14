"""Regression tests for constructor DI fallback behavior."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import mugen.core.plugin.command.clear_history.cp_ext as cp_ext_module
import mugen.core.plugin.context.persona.ctx_ext as ctx_ext_module
import mugen.core.plugin.message_handler.text.mh_ext as mh_ext_module
import mugen.core.plugin.whatsapp.wacapi.ipc_ext as wacapi_ipc_ext_module
from mugen.core.plugin.command.clear_history.cp_ext import (
    ClearChatHistoryICPExtension,
)
from mugen.core.plugin.context.persona.ctx_ext import SystemPersonaCTXExtension
from mugen.core.plugin.message_handler.text.mh_ext import DefaultTextMHExtension
from mugen.core.plugin.whatsapp.wacapi.ipc_ext import WhatsAppWACAPIIPCExtension


class TestSystemPersonaContextFallbacks(unittest.TestCase):
    """Tests constructor fallback behavior for system persona context extension."""

    def test_explicit_config_bypasses_provider(self) -> None:
        config = SimpleNamespace()
        fallback_config = []
        with patch.object(
            ctx_ext_module.di,
            "container",
            new=SimpleNamespace(config=fallback_config),
        ):
            ext = SystemPersonaCTXExtension(config=config)

        self.assertIs(ext._config, config)

    def test_missing_config_uses_provider(self) -> None:
        fallback_config = SimpleNamespace()
        with patch.object(
            ctx_ext_module.di,
            "container",
            new=SimpleNamespace(config=fallback_config),
        ):
            ext = SystemPersonaCTXExtension()

        self.assertIs(ext._config, fallback_config)


class TestClearHistoryFallbacks(unittest.TestCase):
    """Tests constructor fallback behavior for clear history command extension."""

    def test_explicit_dependencies_bypass_providers(self) -> None:
        config = SimpleNamespace()
        keyval = object()
        fallback_config = []
        fallback_keyval = []

        with (
            patch.object(
                cp_ext_module.di,
                "container",
                new=SimpleNamespace(
                    config=fallback_config,
                    keyval_storage_gateway=fallback_keyval,
                ),
            ),
        ):
            ext = ClearChatHistoryICPExtension(
                config=config,
                keyval_storage_gateway=keyval,
            )

        self.assertIs(ext._config, config)
        self.assertIs(ext._keyval_storage_gateway, keyval)

    def test_missing_dependencies_use_providers(self) -> None:
        fallback_config = SimpleNamespace()
        fallback_keyval = object()

        with (
            patch.object(
                cp_ext_module.di,
                "container",
                new=SimpleNamespace(
                    config=fallback_config,
                    keyval_storage_gateway=fallback_keyval,
                ),
            ),
        ):
            ext = ClearChatHistoryICPExtension()

        self.assertIs(ext._config, fallback_config)
        self.assertIs(ext._keyval_storage_gateway, fallback_keyval)


class TestDefaultTextMessageHandlerFallbacks(unittest.TestCase):
    """Tests constructor fallback behavior for default text message handler."""

    def test_explicit_dependencies_bypass_providers(self) -> None:
        completion_gateway = object()
        config = SimpleNamespace()
        keyval_storage_gateway = object()
        logging_gateway = object()
        messaging_service = object()
        fallback_completion_gateway = []
        fallback_config = []
        fallback_keyval_storage_gateway = []
        fallback_logging_gateway = []
        fallback_messaging_service = []

        with (
            patch.object(
                mh_ext_module.di,
                "container",
                new=SimpleNamespace(
                    completion_gateway=fallback_completion_gateway,
                    config=fallback_config,
                    keyval_storage_gateway=fallback_keyval_storage_gateway,
                    logging_gateway=fallback_logging_gateway,
                    messaging_service=fallback_messaging_service,
                ),
            ),
        ):
            ext = DefaultTextMHExtension(
                completion_gateway=completion_gateway,
                config=config,
                keyval_storage_gateway=keyval_storage_gateway,
                logging_gateway=logging_gateway,
                messaging_service=messaging_service,
            )

        self.assertIs(ext._completion_gateway, completion_gateway)
        self.assertIs(ext._config, config)
        self.assertIs(ext._keyval_storage_gateway, keyval_storage_gateway)
        self.assertIs(ext._logging_gateway, logging_gateway)
        self.assertIs(ext._messaging_service, messaging_service)

    def test_missing_dependencies_use_providers(self) -> None:
        fallback_completion_gateway = object()
        fallback_config = SimpleNamespace()
        fallback_keyval_storage_gateway = object()
        fallback_logging_gateway = object()
        fallback_messaging_service = object()

        with (
            patch.object(
                mh_ext_module.di,
                "container",
                new=SimpleNamespace(
                    completion_gateway=fallback_completion_gateway,
                    config=fallback_config,
                    keyval_storage_gateway=fallback_keyval_storage_gateway,
                    logging_gateway=fallback_logging_gateway,
                    messaging_service=fallback_messaging_service,
                ),
            ),
        ):
            ext = DefaultTextMHExtension()

        self.assertIs(ext._completion_gateway, fallback_completion_gateway)
        self.assertIs(ext._config, fallback_config)
        self.assertIs(ext._keyval_storage_gateway, fallback_keyval_storage_gateway)
        self.assertIs(ext._logging_gateway, fallback_logging_gateway)
        self.assertIs(ext._messaging_service, fallback_messaging_service)


class TestWhatsAppWacapiIpcFallbacks(unittest.TestCase):
    """Tests constructor fallback behavior for WhatsApp WACAPI IPC extension."""

    def test_explicit_dependencies_bypass_providers(self) -> None:
        whatsapp_client = object()
        config = SimpleNamespace()
        logging_gateway = object()
        messaging_service = object()
        user_service = object()
        fallback_whatsapp_client = []
        fallback_config = []
        fallback_logging_gateway = []
        fallback_messaging_service = []
        fallback_user_service = []

        with (
            patch.object(
                wacapi_ipc_ext_module.di,
                "container",
                new=SimpleNamespace(
                    whatsapp_client=fallback_whatsapp_client,
                    config=fallback_config,
                    logging_gateway=fallback_logging_gateway,
                    messaging_service=fallback_messaging_service,
                    user_service=fallback_user_service,
                ),
            ),
        ):
            ext = WhatsAppWACAPIIPCExtension(
                whatsapp_client=whatsapp_client,
                config=config,
                logging_gateway=logging_gateway,
                messaging_service=messaging_service,
                user_service=user_service,
            )

        self.assertIs(ext._client, whatsapp_client)
        self.assertIs(ext._config, config)
        self.assertIs(ext._logging_gateway, logging_gateway)
        self.assertIs(ext._messaging_service, messaging_service)
        self.assertIs(ext._user_service, user_service)

    def test_missing_dependencies_use_providers(self) -> None:
        fallback_whatsapp_client = object()
        fallback_config = SimpleNamespace()
        fallback_logging_gateway = object()
        fallback_messaging_service = object()
        fallback_user_service = object()

        with (
            patch.object(
                wacapi_ipc_ext_module.di,
                "container",
                new=SimpleNamespace(
                    whatsapp_client=fallback_whatsapp_client,
                    config=fallback_config,
                    logging_gateway=fallback_logging_gateway,
                    messaging_service=fallback_messaging_service,
                    user_service=fallback_user_service,
                ),
            ),
        ):
            ext = WhatsAppWACAPIIPCExtension()

        self.assertIs(ext._client, fallback_whatsapp_client)
        self.assertIs(ext._config, fallback_config)
        self.assertIs(ext._logging_gateway, fallback_logging_gateway)
        self.assertIs(ext._messaging_service, fallback_messaging_service)
        self.assertIs(ext._user_service, fallback_user_service)

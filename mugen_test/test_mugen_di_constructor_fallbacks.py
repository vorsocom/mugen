"""Regression tests for constructor DI fallback behavior."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import mugen.core.plugin.whatsapp.wacapi.ipc_ext as wacapi_ipc_ext_module
from mugen.core.extension.cp.clear_history import ClearChatHistoryICPExtension
from mugen.core.extension.mh.default_text import DefaultTextMHExtension
from mugen.core.plugin.context_engine.service.contributor import PersonaPolicyContributor
from mugen.core.plugin.whatsapp.wacapi.ipc_ext import WhatsAppWACAPIIPCExtension


class TestPersonaPolicyContributorFallbacks(unittest.TestCase):
    """Tests constructor behavior for persona-policy contributor."""

    def test_explicit_config_is_used(self) -> None:
        config = SimpleNamespace()
        contributor = PersonaPolicyContributor(config=config)

        self.assertIs(contributor._config, config)  # pylint: disable=protected-access

    def test_missing_config_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            PersonaPolicyContributor()


class TestClearHistoryFallbacks(unittest.TestCase):
    """Tests constructor behavior for clear history command extension."""

    def test_explicit_dependencies_are_used(self) -> None:
        config = SimpleNamespace(mugen=SimpleNamespace(commands=SimpleNamespace(clear="/clear")))
        provider = object()
        ext = ClearChatHistoryICPExtension(
            config=config,
            context_component_registry_provider=provider,
        )

        self.assertIs(ext._config, config)  # pylint: disable=protected-access
        self.assertIs(  # pylint: disable=protected-access
            ext._context_component_registry_provider,
            provider,
        )

    def test_missing_dependencies_are_rejected(self) -> None:
        with self.assertRaises(TypeError):
            ClearChatHistoryICPExtension()


class TestDefaultTextMessageHandlerFallbacks(unittest.TestCase):
    """Tests constructor behavior for default text message handler."""

    def test_explicit_dependencies_are_used(self) -> None:
        completion_gateway = object()
        config = SimpleNamespace()
        context_engine_service = object()
        logging_gateway = object()
        messaging_service = object()
        ext = DefaultTextMHExtension(
            completion_gateway=completion_gateway,
            config=config,
            context_engine_service=context_engine_service,
            logging_gateway=logging_gateway,
            messaging_service=messaging_service,
        )

        self.assertIs(ext._completion_gateway, completion_gateway)  # pylint: disable=protected-access
        self.assertIs(ext._config, config)  # pylint: disable=protected-access
        self.assertIs(  # pylint: disable=protected-access
            ext._context_engine_service,
            context_engine_service,
        )
        self.assertIs(ext._logging_gateway, logging_gateway)  # pylint: disable=protected-access
        self.assertIs(ext._messaging_service, messaging_service)  # pylint: disable=protected-access

    def test_missing_dependencies_are_rejected(self) -> None:
        with self.assertRaises(TypeError):
            DefaultTextMHExtension()


class TestWhatsAppWacapiIpcFallbacks(unittest.TestCase):
    """Tests constructor fallback behavior for WhatsApp WACAPI IPC extension."""

    def test_explicit_dependencies_bypass_providers(self) -> None:
        whatsapp_client = object()
        config = SimpleNamespace()
        logging_gateway = object()
        relational_storage_gateway = object()
        messaging_service = object()
        user_service = object()
        fallback_whatsapp_client = []
        fallback_config = []
        fallback_logging_gateway = []
        fallback_relational_storage_gateway = []
        fallback_messaging_service = []
        fallback_user_service = []

        with patch.object(
            wacapi_ipc_ext_module.di,
            "container",
            new=SimpleNamespace(
                whatsapp_client=fallback_whatsapp_client,
                config=fallback_config,
                logging_gateway=fallback_logging_gateway,
                relational_storage_gateway=fallback_relational_storage_gateway,
                messaging_service=fallback_messaging_service,
                user_service=fallback_user_service,
            ),
        ):
            ext = WhatsAppWACAPIIPCExtension(
                whatsapp_client=whatsapp_client,
                config=config,
                logging_gateway=logging_gateway,
                relational_storage_gateway=relational_storage_gateway,
                messaging_service=messaging_service,
                user_service=user_service,
            )

        self.assertIs(ext._client, whatsapp_client)  # pylint: disable=protected-access
        self.assertIs(ext._config, config)  # pylint: disable=protected-access
        self.assertIs(ext._logging_gateway, logging_gateway)  # pylint: disable=protected-access
        self.assertIs(  # pylint: disable=protected-access
            ext._relational_storage_gateway,
            relational_storage_gateway,
        )
        self.assertIs(ext._messaging_service, messaging_service)  # pylint: disable=protected-access
        self.assertIs(ext._user_service, user_service)  # pylint: disable=protected-access

    def test_missing_dependencies_use_providers(self) -> None:
        fallback_whatsapp_client = object()
        fallback_config = SimpleNamespace()
        fallback_logging_gateway = object()
        fallback_relational_storage_gateway = object()
        fallback_messaging_service = object()
        fallback_user_service = object()

        with patch.object(
            wacapi_ipc_ext_module.di,
            "container",
            new=SimpleNamespace(
                whatsapp_client=fallback_whatsapp_client,
                config=fallback_config,
                logging_gateway=fallback_logging_gateway,
                relational_storage_gateway=fallback_relational_storage_gateway,
                messaging_service=fallback_messaging_service,
                user_service=fallback_user_service,
            ),
        ):
            ext = WhatsAppWACAPIIPCExtension()

        self.assertIs(ext._client, fallback_whatsapp_client)  # pylint: disable=protected-access
        self.assertIs(ext._config, fallback_config)  # pylint: disable=protected-access
        self.assertIs(ext._logging_gateway, fallback_logging_gateway)  # pylint: disable=protected-access
        self.assertIs(  # pylint: disable=protected-access
            ext._relational_storage_gateway,
            fallback_relational_storage_gateway,
        )
        self.assertIs(ext._messaging_service, fallback_messaging_service)  # pylint: disable=protected-access
        self.assertIs(ext._user_service, fallback_user_service)  # pylint: disable=protected-access

"""Unit tests for mugen module provider helpers and CP extension branch."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from quart import Quart

import mugen as mugen_mod
from mugen.core.contract.extension.cp import ICPExtension


class _DummyCPExt(ICPExtension):
    @property
    def platforms(self) -> list[str]:
        return []

    @property
    def commands(self) -> list[str]:
        return ["ping"]

    async def process_message(
        self,
        message: str,
        room_id: str,
        user_id: str,
    ) -> list[dict] | None:
        return [{"message": message, "room_id": room_id, "user_id": user_id}]


_DummyCPExt.__module__ = "cp_ext"


class TestMugenInitProvidersAndCPBranch(unittest.IsolatedAsyncioTestCase):
    """Covers provider helper functions and cp registration success branch."""

    def test_provider_helpers_read_expected_container_members(self) -> None:
        fake_container = SimpleNamespace(
            config="cfg",
            matrix_client="matrix-client",
            web_client="web-client",
        )
        with patch.object(mugen_mod.di, "container", fake_container):
            self.assertEqual(mugen_mod._config_provider(), "cfg")  # pylint: disable=protected-access
            self.assertEqual(mugen_mod._matrix_provider(), "matrix-client")  # pylint: disable=protected-access
            self.assertEqual(mugen_mod._web_provider(), "web-client")  # pylint: disable=protected-access

    async def test_register_extensions_registers_cp_extension_when_supported(
        self,
    ) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[SimpleNamespace(type="cp", path="cp_ext:_DummyCPExt")]
                )
            )
        )
        messaging_service = SimpleNamespace(register_cp_extension=Mock())
        ipc_service = SimpleNamespace(register_ipc_extension=Mock())
        platform_service = SimpleNamespace(extension_supported=Mock(return_value=True))

        with patch.dict("sys.modules", {"cp_ext": Mock(_DummyCPExt=_DummyCPExt)}):
            await mugen_mod.register_extensions(
                app=app,
                config_provider=lambda: config,
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: app.logger,
                messaging_provider=lambda: messaging_service,
                platform_provider=lambda: platform_service,
            )

        platform_service.extension_supported.assert_called_once()
        messaging_service.register_cp_extension.assert_called_once()
        self.assertIsInstance(
            messaging_service.register_cp_extension.call_args.args[0],
            _DummyCPExt,
        )

    async def test_register_extensions_skips_unsupported_cp_and_missing_core_plugins(
        self,
    ) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    core=SimpleNamespace(),
                    extensions=[SimpleNamespace(type="cp", path="cp_ext:_DummyCPExt")],
                )
            )
        )
        messaging_service = SimpleNamespace(register_cp_extension=Mock())
        ipc_service = SimpleNamespace(register_ipc_extension=Mock())
        platform_service = SimpleNamespace(extension_supported=Mock(return_value=False))

        with (
            patch.dict("sys.modules", {"cp_ext": Mock(_DummyCPExt=_DummyCPExt)}),
            self.assertLogs("test_app", level="WARNING") as logger,
        ):
            await mugen_mod.register_extensions(
                app=app,
                config_provider=lambda: config,
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: app.logger,
                messaging_provider=lambda: messaging_service,
                platform_provider=lambda: platform_service,
            )

        platform_service.extension_supported.assert_called_once()
        messaging_service.register_cp_extension.assert_not_called()
        self.assertIn(
            "WARNING:test_app:Extension not supported by active platforms: cp_ext:_DummyCPExt.",
            logger.output,
        )

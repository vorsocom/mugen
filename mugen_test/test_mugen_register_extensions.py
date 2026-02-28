"""Provides unit tests for mugen.register_extensions."""

# pylint: disable=too-many-lines

from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart

import mugen as mugen_mod
from mugen import (
    BootstrapConfigError,
    ExtensionLoadError,
    register_extensions as _register_extensions,
)
from mugen.core.contract.extension.ct import ICTExtension
from mugen.core.contract.extension.ctx import ICTXExtension
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.extension.rag import IRAGExtension
from mugen.core.contract.extension.rpp import IRPPExtension
from mugen.core.contract.service.ipc import IPCCommandRequest, IPCHandlerResult


def _ipc_provider():
    return SimpleNamespace(register_ipc_extension=unittest.mock.Mock())


def _messaging_provider():
    return SimpleNamespace(
        register_cp_extension=unittest.mock.Mock(),
        register_ct_extension=unittest.mock.Mock(),
        register_ctx_extension=unittest.mock.Mock(),
        register_mh_extension=unittest.mock.Mock(),
        register_rag_extension=unittest.mock.Mock(),
        register_rpp_extension=unittest.mock.Mock(),
    )


def _platform_provider():
    return SimpleNamespace(extension_supported=unittest.mock.Mock(return_value=True))


def _platform_provider_for_config(config: SimpleNamespace):
    active = set(getattr(config.mugen, "platforms", []))

    def _supported(ext) -> bool:
        raw_platforms = getattr(ext, "platforms", None)
        if raw_platforms is None:
            return True
        try:
            ext_platforms = set(raw_platforms)
        except TypeError:
            return True
        if not ext_platforms:
            return True
        if not active:
            return True
        return bool(ext_platforms.intersection(active))

    return SimpleNamespace(
        extension_supported=unittest.mock.Mock(side_effect=_supported)
    )


async def register_extensions(*args, **kwargs):
    """Wrapper providing deterministic defaults for extension wiring tests."""
    cfg_provider = kwargs.get("config_provider")
    cfg = cfg_provider() if callable(cfg_provider) else None
    kwargs.setdefault("ipc_provider", _ipc_provider)
    kwargs.setdefault("messaging_provider", _messaging_provider)
    if "platform_provider" not in kwargs:
        if cfg is not None and hasattr(cfg, "mugen"):
            kwargs["platform_provider"] = lambda: _platform_provider_for_config(cfg)
        else:
            kwargs["platform_provider"] = _platform_provider
    return await _register_extensions(*args, **kwargs)


# pylint: disable=too-many-public-methods
class TestMuGenInitRegisterExtensions(unittest.IsolatedAsyncioTestCase):
    """Unit tests for mugen.register_extensions."""

    async def test_extension_enabled_parses_common_string_values(self) -> None:
        """String-form enable flags should be parsed deterministically."""
        self.assertTrue(
            mugen_mod._extension_enabled(SimpleNamespace(enabled=" yes "))  # pylint: disable=protected-access
        )
        self.assertFalse(
            mugen_mod._extension_enabled(SimpleNamespace(enabled="OFF"))  # pylint: disable=protected-access
        )
        self.assertTrue(
            mugen_mod._extension_enabled(SimpleNamespace(enabled="maybe"))  # pylint: disable=protected-access
        )

    async def test_split_extension_path_rejects_invalid_values(self) -> None:
        """Extension path helper should reject empty and malformed class targets."""
        with self.assertRaises(ValueError):
            mugen_mod._split_extension_path("")  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            mugen_mod._split_extension_path("module:")  # pylint: disable=protected-access

    async def test_plugin_config_unavailable(self) -> None:
        """Test effects of missing plugins configuration."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(mugen=SimpleNamespace())

        with self.assertLogs(logger="test_app", level="ERROR") as logger:
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[0],
                "ERROR:test_app:Plugin configuration attribute error.",
            )

    async def test_plugin_config_available(self) -> None:
        """Test effects of having plugins configuration."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    core=SimpleNamespace(
                        plugins=[],
                    ),
                )
            )
        )

        with self.assertLogs(logger="test_app", level="DEBUG") as logger:
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Adding plugins for loading.",
            )

    async def test_plugin_config_none_normalizes_to_empty_list(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    core=SimpleNamespace(
                        plugins=None,
                    ),
                )
            )
        )

        await register_extensions(
            app=app,
            config_provider=lambda: config,
            logger_provider=lambda: app.logger,
        )

    async def test_plugin_config_invalid_type_raises(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    core=SimpleNamespace(
                        plugins="not-a-list",
                    ),
                )
            )
        )

        with self.assertRaises(BootstrapConfigError):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_extension_config_unavailable(self) -> None:
        """Test effects of missing extensions configuration."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(mugen=SimpleNamespace())

        with self.assertLogs(logger="test_app", level="ERROR") as logger:
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[1],
                "ERROR:test_app:Extension configuration attribute error.",
            )

    async def test_extension_config_available(self) -> None:
        """Test effects of having extensions configuration."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[],
                )
            )
        )

        with self.assertLogs(logger="test_app", level="DEBUG") as logger:
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[1],
                "DEBUG:test_app:Adding extensions for loading.",
            )

    async def test_extension_config_none_normalizes_to_empty_list(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=None,
                )
            )
        )

        await register_extensions(
            app=app,
            config_provider=lambda: config,
            logger_provider=lambda: app.logger,
        )

    async def test_extension_config_invalid_type_raises(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions="bad",
                )
            )
        )

        with self.assertRaises(BootstrapConfigError):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_disabled_core_plugin_is_skipped(self) -> None:
        """Disabled core plugins should be skipped without loading/importing."""
        app = Quart("test_app")
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    core=SimpleNamespace(
                        plugins=[
                            SimpleNamespace(
                                type="ct",
                                path="disabled.core.plugin",
                                enabled=False,
                            )
                        ],
                    ),
                )
            )
        )

        with (
            self.assertLogs(logger="test_app", level="INFO") as logger,
            unittest.mock.patch("mugen.import_module") as import_module_mock,
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

        import_module_mock.assert_not_called()
        self.assertIn(
            "INFO:test_app:Skipping disabled extension: disabled.core.plugin (ct).",
            logger.output,
        )

    async def test_disabled_third_party_extension_is_skipped(self) -> None:
        """Disabled third-party extensions should be skipped without import."""
        app = Quart("test_app")
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="ipc",
                            path="disabled.third.party.extension",
                            enabled=False,
                        )
                    ],
                ),
            )
        )

        with (
            self.assertLogs(logger="test_app", level="INFO") as logger,
            unittest.mock.patch("mugen.import_module") as import_module_mock,
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

        import_module_mock.assert_not_called()
        self.assertIn(
            "INFO:test_app:Skipping disabled extension:"
            " disabled.third.party.extension (ipc).",
            logger.output,
        )

    async def test_import_module_failure(self) -> None:
        """Test effects of module import failing."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="extension_type",
                            path="extension.module",
                        )
                    ],
                )
            )
        )

        with (
            self.assertLogs(logger="test_app"),
            self.assertRaises(ExtensionLoadError),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_invalid_extension_path_format_raises(self) -> None:
        """Invalid extension paths should fail before import/registration."""
        app = Quart("test_app")
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="ct",
                            path="invalid.module.path:",
                        )
                    ],
                )
            )
        )

        with (
            self.assertLogs(logger="test_app"),
            self.assertRaises(ExtensionLoadError),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_missing_subclass(self) -> None:
        """Test effects of missing subclass of the relevant extension type."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="ct",
                            path="ct_ext",
                        )
                    ],
                )
            )
        )


        with (
            self.assertLogs(logger="test_app"),
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "ct_ext": unittest.mock.Mock(),
                },
            ),
            unittest.mock.patch(
                target="mugen.core.contract.extension.ct.ICTExtension.__subclasses__",
                return_value=[],
            ),
            self.assertRaises(ExtensionLoadError),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_incomplete_subclass_implmentation(self) -> None:
        """Test effects of incomplete subclass implementation."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="ct",
                            path="ct_ext",
                        )
                    ],
                )
            )
        )

        class DummyExtensionClass(ICTExtension):
            """Dummy extension class."""

            __module__ = "ct_ext"


        with (
            self.assertLogs(logger="test_app"),
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "ct_ext": unittest.mock.Mock(),
                },
            ),
            unittest.mock.patch(
                target="mugen.core.contract.extension.ct.ICTExtension.__subclasses__",
                return_value=[DummyExtensionClass],
            ),
            self.assertRaises(ExtensionLoadError),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_register_extension_with_explicit_class_path(self) -> None:
        """module:ClassName extension paths should resolve deterministically."""
        app = Quart("test_app")
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="ct",
                            path="ct_ext:TargetCTExtension",
                        )
                    ],
                )
            )
        )

        class TargetCTExtension(ICTExtension):
            __module__ = "ct_ext"

            @property
            def platforms(self) -> list[str]:
                return []

            @property
            def triggers(self) -> list[str]:
                return ["target"]

            async def process_message(
                self,
                message: str,
                role: str,
                room_id: str,
                user_id: str,
            ) -> None:
                _ = (message, role, room_id, user_id)

        class OtherCTExtension(ICTExtension):
            __module__ = "ct_ext"

            @property
            def platforms(self) -> list[str]:
                return []

            @property
            def triggers(self) -> list[str]:
                return ["other"]

            async def process_message(
                self,
                message: str,
                role: str,
                room_id: str,
                user_id: str,
            ) -> None:
                _ = (message, role, room_id, user_id)

        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "ct_ext": unittest.mock.Mock(
                        TargetCTExtension=TargetCTExtension,
                        OtherCTExtension=OtherCTExtension,
                    ),
                },
            ),
            unittest.mock.patch(
                target="mugen.core.contract.extension.ct.ICTExtension.__subclasses__",
                return_value=[OtherCTExtension, TargetCTExtension],
            ),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

        self.assertIn(
            "DEBUG:test_app:Registered CT extension: ct_ext:TargetCTExtension.",
            logger.output,
        )

    async def test_extension_class_path_missing_target_class(self) -> None:
        """module:ClassName should fail when class target is missing."""
        app = Quart("test_app")
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="ct",
                            path="ct_ext:MissingClass",
                        )
                    ],
                )
            )
        )

        with (
            self.assertLogs(logger="test_app"),
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "ct_ext": unittest.mock.Mock(),
                },
            ),
            self.assertRaises(ExtensionLoadError),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_extension_class_path_with_wrong_interface(self) -> None:
        """module:ClassName should fail when class does not implement interface."""
        app = Quart("test_app")
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="ct",
                            path="ct_ext:NotCTExtension",
                        )
                    ],
                )
            )
        )

        class NotCTExtension:  # pylint: disable=too-few-public-methods
            __module__ = "ct_ext"

        with (
            self.assertLogs(logger="test_app"),
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "ct_ext": unittest.mock.Mock(NotCTExtension=NotCTExtension),
                },
            ),
            self.assertRaises(ExtensionLoadError),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_extension_without_class_path_fails_when_ambiguous(self) -> None:
        """module-only extension path should fail when multiple classes match."""
        app = Quart("test_app")
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="ct",
                            path="ct_ext",
                        )
                    ],
                )
            )
        )

        class FirstCTExtension(ICTExtension):
            __module__ = "ct_ext"

            @property
            def platforms(self) -> list[str]:
                return []

            @property
            def triggers(self) -> list[str]:
                return ["first"]

            async def process_message(
                self,
                message: str,
                role: str,
                room_id: str,
                user_id: str,
            ) -> None:
                _ = (message, role, room_id, user_id)

        class SecondCTExtension(ICTExtension):
            __module__ = "ct_ext"

            @property
            def platforms(self) -> list[str]:
                return []

            @property
            def triggers(self) -> list[str]:
                return ["second"]

            async def process_message(
                self,
                message: str,
                role: str,
                room_id: str,
                user_id: str,
            ) -> None:
                _ = (message, role, room_id, user_id)

        with (
            self.assertLogs(logger="test_app"),
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "ct_ext": unittest.mock.Mock(),
                },
            ),
            unittest.mock.patch(
                target="mugen.core.contract.extension.ct.ICTExtension.__subclasses__",
                return_value=[FirstCTExtension, SecondCTExtension],
            ),
            self.assertRaises(ExtensionLoadError),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_register_unsupported_conversational_trigger_extension(self) -> None:
        """Test registration of unsupported conversational trigger extension."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="ct",
                            path="ct_ext",
                        )
                    ],
                ),
                platforms=["matrix"],
            )
        )

        class DummyExtensionClass(ICTExtension):
            """Dummy extension class."""

            __module__ = "ct_ext"

            @property
            def platforms(self) -> list[str]:
                """Get the platform that the extension is targeting."""
                return ["unsupported_platform"]

            @property
            def triggers(self) -> list[str]:
                """Get the list of triggers that activate the service provider."""

            async def process_message(
                self,
                message: str,
                role: str,
                room_id: str,
                user_id: str,
            ) -> None:
                """Process message for conversational triggers."""


        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "ct_ext": unittest.mock.Mock(),
                },
            ),
            unittest.mock.patch(
                target="mugen.core.contract.extension.ct.ICTExtension.__subclasses__",
                return_value=[DummyExtensionClass],
            ),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[2],
                "WARNING:test_app:Extension not supported by active platforms: ct_ext.",
            )

    async def test_register_supported_conversational_trigger_extension(self) -> None:
        """Test registration of supported conversational trigger extension."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="ct",
                            path="ct_ext",
                        )
                    ],
                ),
            )
        )

        class DummyExtensionClass(ICTExtension):
            """Dummy extension class."""

            __module__ = "ct_ext"

            @property
            def platforms(self) -> list[str]:
                """Get the platform that the extension is targeting."""

            @property
            def triggers(self) -> list[str]:
                """Get the list of triggers that activate the service provider."""

            async def process_message(
                self,
                message: str,
                role: str,
                room_id: str,
                user_id: str,
            ) -> None:
                """Process message for conversational triggers."""


        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "ct_ext": unittest.mock.Mock(),
                },
            ),
            unittest.mock.patch(
                target="mugen.core.contract.extension.ct.ICTExtension.__subclasses__",
                return_value=[DummyExtensionClass],
            ),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[2],
                "DEBUG:test_app:Registered CT extension: ct_ext.",
            )

    async def test_register_unsupported_context_extension(self) -> None:
        """Test registration of unsupported context extension."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="ctx",
                            path="ctx_ext",
                        )
                    ],
                ),
                platforms=["matrix"],
            )
        )

        class DummyExtensionClass(ICTXExtension):
            """Dummy extension class."""

            __module__ = "ctx_ext"

            @property
            def platforms(self) -> list[str]:
                """Get the platform that the extension is targeting."""
                return ["unsupported_platform"]

            def get_context(self, user_id: str) -> list[dict]:
                """Provides conversation context through system messages."""


        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "ctx_ext": unittest.mock.Mock(),
                },
            ),
            unittest.mock.patch(
                target="mugen.core.contract.extension.ctx.ICTXExtension.__subclasses__",
                return_value=[DummyExtensionClass],
            ),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[2],
                "WARNING:test_app:Extension not supported by active platforms:"
                " ctx_ext.",
            )

    async def test_register_supported_context_extension(self) -> None:
        """Test registration of supported context extension."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="ctx",
                            path="ctx_ext",
                        )
                    ],
                ),
            )
        )

        class DummyExtensionClass(ICTXExtension):
            """Dummy extension class."""

            __module__ = "ctx_ext"

            @property
            def platforms(self) -> list[str]:
                """Get the platform that the extension is targeting."""

            def get_context(self, user_id: str) -> list[dict]:
                """Provides conversation context through system messages."""


        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "ctx_ext": unittest.mock.Mock(),
                },
            ),
            unittest.mock.patch(
                target="mugen.core.contract.extension.ctx.ICTXExtension.__subclasses__",
                return_value=[DummyExtensionClass],
            ),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[2],
                "DEBUG:test_app:Registered CTX extension: ctx_ext.",
            )

    async def test_register_unsupported_framework_extension(self) -> None:
        """Test registration of unsupported framework extension."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="fw",
                            path="fw_ext",
                        )
                    ],
                ),
                platforms=["matrix"],
            )
        )

        class DummyExtensionClass(IFWExtension):
            """Dummy extension class."""

            __module__ = "fw_ext"

            @property
            def platforms(self) -> list[str]:
                """Get the platform that the extension is targeting."""
                return ["unsupported_platform"]

            async def setup(self, app: Quart) -> None:
                """Perform extension setup."""


        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "fw_ext": unittest.mock.Mock(),
                },
            ),
            unittest.mock.patch(
                target="mugen.core.contract.extension.fw.IFWExtension.__subclasses__",
                return_value=[DummyExtensionClass],
            ),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[2],
                "WARNING:test_app:Extension not supported by active platforms: fw_ext.",
            )

    async def test_register_supported_framework_extension(self) -> None:
        """Test registration of supported framework extension."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="fw",
                            path="fw_ext",
                        )
                    ],
                ),
            )
        )

        class DummyExtensionClass(IFWExtension):
            """Dummy extension class."""

            __module__ = "fw_ext"

            @property
            def platforms(self) -> list[str]:
                """Get the platform that the extension is targeting."""

            async def setup(self, app: Quart) -> None:
                """Perform extension setup."""


        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "fw_ext": unittest.mock.Mock(),
                },
            ),
            unittest.mock.patch(
                target="mugen.core.contract.extension.fw.IFWExtension.__subclasses__",
                return_value=[DummyExtensionClass],
            ),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[2],
                "DEBUG:test_app:Registered FW extension: fw_ext.",
            )

    async def test_register_unsupported_interprocess_communication_extension(
        self,
    ) -> None:
        """Test registration of unsupported inter-process communication extension."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="ipc",
                            path="ipc_ext",
                        )
                    ],
                ),
                platforms=["matrix"],
            )
        )

        class DummyExtensionClass(IIPCExtension):
            """Dummy extension class."""

            __module__ = "ipc_ext"

            @property
            def platforms(self) -> list[str]:
                """Get the platform that the extension is targeting."""
                return ["unsupported_platform"]

            @property
            def ipc_commands(self) -> list[str]:
                """Get the list of ipc commands processed by this provider.."""

            async def process_ipc_command(
                self,
                request: IPCCommandRequest,
            ) -> IPCHandlerResult:
                """Process an IPC command."""
                return IPCHandlerResult(
                    handler=type(self).__name__,
                    response={"command": request.command},
                )


        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "ipc_ext": unittest.mock.Mock(),
                },
            ),
            unittest.mock.patch(
                target="mugen.core.contract.extension.ipc.IIPCExtension.__subclasses__",
                return_value=[DummyExtensionClass],
            ),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[2],
                "WARNING:test_app:Extension not supported by active platforms:"
                " ipc_ext.",
            )

    async def test_register_supported_interprocess_communication_extension(
        self,
    ) -> None:
        """Test registration of supported inter-process communication extension."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="ipc",
                            path="ipc_ext",
                        )
                    ],
                ),
            )
        )

        class DummyExtensionClass(IIPCExtension):
            """Dummy extension class."""

            __module__ = "ipc_ext"

            @property
            def platforms(self) -> list[str]:
                """Get the platform that the extension is targeting."""

            @property
            def ipc_commands(self) -> list[str]:
                """Get the list of ipc commands processed by this provider.."""

            async def process_ipc_command(
                self,
                request: IPCCommandRequest,
            ) -> IPCHandlerResult:
                """Process an IPC command."""
                return IPCHandlerResult(
                    handler=type(self).__name__,
                    response={"command": request.command},
                )


        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "ipc_ext": unittest.mock.Mock(),
                },
            ),
            unittest.mock.patch(
                target="mugen.core.contract.extension.ipc.IIPCExtension.__subclasses__",
                return_value=[DummyExtensionClass],
            ),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[2],
                "DEBUG:test_app:Registered IPC extension: ipc_ext.",
            )

    async def test_register_unsupported_message_handler_extension(self) -> None:
        """Test registration of unsupported message handler extension."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="mh",
                            path="mh_ext",
                        )
                    ],
                ),
                platforms=["matrix"],
            )
        )

        class DummyExtensionClass(IMHExtension):
            """Dummy extension class."""

            __module__ = "mh_ext"

            @property
            def platforms(self) -> list[str]:
                """Get the platform that the extension is targeting."""
                return ["unsupported_platform"]

            @property
            def message_types(self) -> list[str]:
                """Get the list of message types that the extension handles."""

            # pylint: disable=too-many-arguments
            # pylint: disable=too-many-positional-arguments
            async def handle_message(
                self,
                platform: str,
                room_id: str,
                sender: str,
                message: dict | str,
                message_context: list[dict] = None,
            ) -> None:
                """Handle a message."""


        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "mh_ext": unittest.mock.Mock(),
                },
            ),
            unittest.mock.patch(
                target="mugen.core.contract.extension.mh.IMHExtension.__subclasses__",
                return_value=[DummyExtensionClass],
            ),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[2],
                "WARNING:test_app:Extension not supported by active platforms: mh_ext.",
            )

    async def test_register_supported_message_handler_extension(self) -> None:
        """Test registration of supported message handler extension."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="mh",
                            path="mh_ext",
                        )
                    ],
                ),
            )
        )

        class DummyExtensionClass(IMHExtension):
            """Dummy extension class."""

            __module__ = "mh_ext"

            @property
            def platforms(self) -> list[str]:
                """Get the platform that the extension is targeting."""

            @property
            def message_types(self) -> list[str]:
                """Get the list of message types that the extension handles."""

            # pylint: disable=too-many-arguments
            # pylint: disable=too-many-positional-arguments
            async def handle_message(
                self,
                platform: str,
                room_id: str,
                sender: str,
                message: dict | str,
                message_context: list[dict] = None,
            ) -> None:
                """Handle a message."""


        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "mh_ext": unittest.mock.Mock(),
                },
            ),
            unittest.mock.patch(
                target="mugen.core.contract.extension.mh.IMHExtension.__subclasses__",
                return_value=[DummyExtensionClass],
            ),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[2],
                "DEBUG:test_app:Registered MH extension: mh_ext.",
            )

    async def test_register_unsupported_retrieval_augnmented_generation_extension(
        self,
    ) -> None:
        """Test registration of unsupported retrieval augmented generation extension."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="rag",
                            path="rag_ext",
                        )
                    ],
                ),
                platforms=["matrix"],
            )
        )

        class DummyExtensionClass(IRAGExtension):
            """Dummy extension class."""

            __module__ = "rag_ext"

            @property
            def platforms(self) -> list[str]:
                """Get the platform that the extension is targeting."""
                return ["unsupported_platform"]

            @property
            def cache_key(self) -> str:
                """Get key used to access the provider cache."""

            async def retrieve(
                self,
                sender: str,
                message: str,
                chat_history: dict,
            ) -> None:
                """Perform knowledge retrieval."""


        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "rag_ext": unittest.mock.Mock(),
                },
            ),
            unittest.mock.patch(
                target="mugen.core.contract.extension.rag.IRAGExtension.__subclasses__",
                return_value=[DummyExtensionClass],
            ),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[2],
                "WARNING:test_app:Extension not supported by active platforms:"
                " rag_ext.",
            )

    async def test_register_supported_retrieval_augnmented_generation_extension(
        self,
    ) -> None:
        """Test registration of supported retrieval augmented generation extension."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="rag",
                            path="rag_ext",
                        )
                    ],
                ),
            )
        )

        class DummyExtensionClass(IRAGExtension):
            """Dummy extension class."""

            __module__ = "rag_ext"

            @property
            def platforms(self) -> list[str]:
                """Get the platform that the extension is targeting."""

            @property
            def cache_key(self) -> str:
                """Get key used to access the provider cache."""

            async def retrieve(
                self,
                sender: str,
                message: str,
                chat_history: dict,
            ) -> None:
                """Perform knowledge retrieval."""


        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "rag_ext": unittest.mock.Mock(),
                },
            ),
            unittest.mock.patch(
                target="mugen.core.contract.extension.rag.IRAGExtension.__subclasses__",
                return_value=[DummyExtensionClass],
            ),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[2],
                "DEBUG:test_app:Registered RAG extension: rag_ext.",
            )

    async def test_register_unsupported_response_preprocessor_extension(self) -> None:
        """Test registration of unsupported response pre-processor extension."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="rpp",
                            path="rpp_ext",
                        )
                    ],
                ),
                platforms=["matrix"],
            )
        )

        class DummyExtensionClass(IRPPExtension):
            """Dummy extension class."""

            __module__ = "rpp_ext"

            @property
            def platforms(self) -> list[str]:
                """Get the platform that the extension is targeting."""
                return ["unsupported_platform"]

            async def preprocess_response(
                self,
                room_id: str,
                user_id: str,
                assistant_response: str,
            ) -> str:
                """Preprocess the assistant response."""


        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "rpp_ext": unittest.mock.Mock(),
                },
            ),
            unittest.mock.patch(
                target="mugen.core.contract.extension.rpp.IRPPExtension.__subclasses__",
                return_value=[DummyExtensionClass],
            ),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[2],
                "WARNING:test_app:Extension not supported by active platforms:"
                " rpp_ext.",
            )

    async def test_register_supported_response_preprocessor_extension(self) -> None:
        """Test registration of supported response pre-processor extension."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="rpp",
                            path="rpp_ext",
                        )
                    ],
                ),
            )
        )

        class DummyExtensionClass(IRPPExtension):
            """Dummy extension class."""

            __module__ = "rpp_ext"

            @property
            def platforms(self) -> list[str]:
                """Get the platform that the extension is targeting."""

            async def preprocess_response(
                self,
                room_id: str,
                user_id: str,
                assistant_response: str,
            ) -> str:
                """Preprocess the assistant response."""


        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "rpp_ext": unittest.mock.Mock(),
                },
            ),
            unittest.mock.patch(
                target="mugen.core.contract.extension.rpp.IRPPExtension.__subclasses__",
                return_value=[DummyExtensionClass],
            ),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
            self.assertEqual(
                logger.output[2],
                "DEBUG:test_app:Registered RPP extension: rpp_ext.",
            )

    async def test_unknown_extension_type(self) -> None:
        """Test effects of unknown extension type."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="xxx",
                            path="xxx_ext",
                        )
                    ],
                )
            )
        )

        # pylint: disable=too-few-public-methods
        class DummyExtensionClass:
            """Dummy extension class."""

            __module__ = "xxx_ext"


        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "xxx_ext": unittest.mock.Mock(),
                },
            ),
            self.assertRaises(ExtensionLoadError),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )
        self.assertTrue(
            any("Unknown extension type: xxx." in line for line in logger.output)
        )

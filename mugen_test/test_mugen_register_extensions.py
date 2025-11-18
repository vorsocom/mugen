"""Provides unit tests for mugen.register_extensions."""

# pylint: disable=too-many-lines

from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart

from mugen import register_extensions
from mugen.core.contract.extension.ct import ICTExtension
from mugen.core.contract.extension.ctx import ICTXExtension
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.extension.rag import IRAGExtension
from mugen.core.contract.extension.rpp import IRPPExtension


# pylint: disable=too-many-public-methods
class TestMuGenInitRegisterExtensions(unittest.IsolatedAsyncioTestCase):
    """Unit tests for mugen.register_extensions."""

    async def test_plugin_config_unavailable(self) -> None:
        """Test effects of missing plugins configuration."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(mugen=SimpleNamespace())

        with self.assertLogs(logger="test_app", level="ERROR") as logger:
            await register_extensions(config=config, logger=app.logger)
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
            await register_extensions(config=config, logger=app.logger)
            self.assertEqual(
                logger.output[0],
                "DEBUG:test_app:Adding plugins for loading.",
            )

    async def test_extension_config_unavailable(self) -> None:
        """Test effects of missing extensions configuration."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(mugen=SimpleNamespace())

        with self.assertLogs(logger="test_app", level="ERROR") as logger:
            await register_extensions(config=config, logger=app.logger)
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
            await register_extensions(config=config, logger=app.logger)
            self.assertEqual(
                logger.output[1],
                "DEBUG:test_app:Adding extensions for loading.",
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
            self.assertRaises(SystemExit),
        ):
            await register_extensions(config=config, logger=app.logger)

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

        sc = unittest.mock.Mock
        sc.return_value = []

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
                new_callable=sc,
            ),
            self.assertRaises(SystemExit),
        ):
            await register_extensions(config=config, logger=app.logger)

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

        sc = unittest.mock.Mock
        sc.return_value = [DummyExtensionClass]

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
                new_callable=sc,
            ),
            self.assertRaises(SystemExit),
        ):
            await register_extensions(config=config, logger=app.logger)

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
                platforms=["telnet"],
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

        sc = unittest.mock.Mock
        sc.return_value = [DummyExtensionClass]

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
                new_callable=sc,
            ),
        ):
            await register_extensions(config=config, logger=app.logger)
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

        sc = unittest.mock.Mock
        sc.return_value = [DummyExtensionClass]

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
                new_callable=sc,
            ),
        ):
            await register_extensions(config=config, logger=app.logger)
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
                platforms=["telnet"],
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

        sc = unittest.mock.Mock
        sc.return_value = [DummyExtensionClass]

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
                new_callable=sc,
            ),
        ):
            await register_extensions(config=config, logger=app.logger)
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

        sc = unittest.mock.Mock
        sc.return_value = [DummyExtensionClass]

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
                new_callable=sc,
            ),
        ):
            await register_extensions(config=config, logger=app.logger)
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
                platforms=["telnet"],
            )
        )

        class DummyExtensionClass(IFWExtension):
            """Dummy extension class."""

            __module__ = "fw_ext"

            @property
            def platforms(self) -> list[str]:
                """Get the platform that the extension is targeting."""
                return ["unsupported_platform"]

            async def setup(self) -> None:
                """Perform extension setup."""

        sc = unittest.mock.Mock
        sc.return_value = [DummyExtensionClass]

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
                new_callable=sc,
            ),
        ):
            await register_extensions(config=config, logger=app.logger)
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

            async def setup(self) -> None:
                """Perform extension setup."""

        sc = unittest.mock.Mock
        sc.return_value = [DummyExtensionClass]

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
                new_callable=sc,
            ),
        ):
            await register_extensions(config=config, logger=app.logger)
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
                platforms=["telnet"],
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

            async def process_ipc_command(self, payload: dict) -> None:
                """Process an IPC command."""

        sc = unittest.mock.Mock
        sc.return_value = [DummyExtensionClass]

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
                new_callable=sc,
            ),
        ):
            await register_extensions(config=config, logger=app.logger)
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

            async def process_ipc_command(self, payload: dict) -> None:
                """Process an IPC command."""

        sc = unittest.mock.Mock
        sc.return_value = [DummyExtensionClass]

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
                new_callable=sc,
            ),
        ):
            await register_extensions(config=config, logger=app.logger)
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
                platforms=["telnet"],
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

            async def handle_message(self, room_id: str, sender: str, message) -> None:
                """Handle a message."""

        sc = unittest.mock.Mock
        sc.return_value = [DummyExtensionClass]

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
                new_callable=sc,
            ),
        ):
            await register_extensions(config=config, logger=app.logger)
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

            async def handle_message(self, room_id: str, sender: str, message) -> None:
                """Handle a message."""

        sc = unittest.mock.Mock
        sc.return_value = [DummyExtensionClass]

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
                new_callable=sc,
            ),
        ):
            await register_extensions(config=config, logger=app.logger)
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
                platforms=["telnet"],
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

            async def retrieve(self, sender: str, message: str, thread: dict) -> None:
                """Perform knowledge retrieval."""

        sc = unittest.mock.Mock
        sc.return_value = [DummyExtensionClass]

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
                new_callable=sc,
            ),
        ):
            await register_extensions(config=config, logger=app.logger)
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

            async def retrieve(self, sender: str, message: str, thread: dict) -> None:
                """Perform knowledge retrieval."""

        sc = unittest.mock.Mock
        sc.return_value = [DummyExtensionClass]

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
                new_callable=sc,
            ),
        ):
            await register_extensions(config=config, logger=app.logger)
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
                platforms=["telnet"],
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
            ) -> str:
                """Preprocess the assistant response."""

        sc = unittest.mock.Mock
        sc.return_value = [DummyExtensionClass]

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
                new_callable=sc,
            ),
        ):
            await register_extensions(config=config, logger=app.logger)
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
            ) -> str:
                """Preprocess the assistant response."""

        sc = unittest.mock.Mock
        sc.return_value = [DummyExtensionClass]

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
                new_callable=sc,
            ),
        ):
            await register_extensions(config=config, logger=app.logger)
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

        sc = unittest.mock.Mock
        sc.return_value = [DummyExtensionClass]

        with (
            self.assertLogs(logger="test_app", level="DEBUG") as logger,
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "xxx_ext": unittest.mock.Mock(),
                },
            ),
        ):
            await register_extensions(config=config, logger=app.logger)
            self.assertEqual(
                logger.output[2],
                "WARNING:test_app:Unknown extension type: xxx.",
            )
            self.assertEqual(
                logger.output[3],
                "WARNING:test_app:Extension not supported by active platforms:"
                " xxx_ext.",
            )

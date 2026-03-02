"""Branch-focused tests for bootstrap/provider token registries."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.bootstrap import extensions as ext_mod
from mugen.core.contract.extension.cp import ICPExtension
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.gateway.completion import ICompletionGateway
from mugen.core.di import provider_registry


class _DummyCPExt(ICPExtension):
    @property
    def platforms(self) -> list[str]:
        return []

    @property
    def commands(self) -> list[str]:
        return []

    async def process_message(self, message: str, room_id: str, user_id: str):
        return None


class _DummyFWExt(IFWExtension):
    @property
    def platforms(self) -> list[str]:
        return []

    async def setup(self, app):  # noqa: ANN001
        return None


class _DummyIPCExt(IIPCExtension):
    @property
    def platforms(self) -> list[str]:
        return []

    @property
    def ipc_commands(self) -> list[str]:
        return ["dummy"]

    async def process_ipc_command(self, request):  # noqa: ANN001
        return None


class _DummyCompletion(ICompletionGateway):
    async def check_readiness(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def get_completion(self, request):  # noqa: ANN001
        return None


class TestExtensionRegistryResolution(unittest.IsolatedAsyncioTestCase):
    def test_parse_bool_default_paths(self) -> None:
        self.assertTrue(ext_mod.parse_bool(object(), default=True))
        self.assertFalse(ext_mod.parse_bool("not-bool", default=False))
        self.assertTrue(ext_mod.parse_bool(" true ", default=False))
        self.assertFalse(ext_mod.parse_bool(" off ", default=True))

    def test_resolve_extension_spec_rejects_invalid_tokens(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "expected a string"):
            ext_mod.resolve_extension_spec(123)
        with self.assertRaisesRegex(RuntimeError, "must be non-empty"):
            ext_mod.resolve_extension_spec("   ")
        with self.assertRaisesRegex(RuntimeError, "module:Class paths are not supported"):
            ext_mod.resolve_extension_spec("module:Class")
        with self.assertRaisesRegex(RuntimeError, "Unknown extension token"):
            ext_mod.resolve_extension_spec("unknown.token")

    def test_resolve_extension_spec_import_shape_and_type_checks(self) -> None:
        class_ref = ext_mod._ExtensionClassRef(  # pylint: disable=protected-access
            extension_type="cp",
            interface=ICPExtension,
            module_path="dummy.module",
            class_name="DummyClass",
        )
        with patch.dict(
            ext_mod._EXTENSION_TOKEN_REGISTRY,  # pylint: disable=protected-access
            {"test.cp.dummy": class_ref},
            clear=False,
        ):
            with patch(
                "mugen.core.bootstrap.extensions.importlib.import_module",
                side_effect=ImportError("missing"),
            ):
                with self.assertRaisesRegex(RuntimeError, "Invalid extension class binding"):
                    ext_mod.resolve_extension_spec("test.cp.dummy")

            with patch(
                "mugen.core.bootstrap.extensions.importlib.import_module",
                return_value=SimpleNamespace(DummyClass=object()),
            ):
                with self.assertRaisesRegex(RuntimeError, "Invalid extension class binding"):
                    ext_mod.resolve_extension_spec("test.cp.dummy")

            with patch(
                "mugen.core.bootstrap.extensions.importlib.import_module",
                return_value=SimpleNamespace(DummyClass=type("Wrong", (), {})),
            ):
                with self.assertRaisesRegex(RuntimeError, "Invalid extension class binding"):
                    ext_mod.resolve_extension_spec("test.cp.dummy")

    def test_resolve_extension_spec_success(self) -> None:
        class_ref = ext_mod._ExtensionClassRef(  # pylint: disable=protected-access
            extension_type="cp",
            interface=ICPExtension,
            module_path="dummy.module",
            class_name="DummyClass",
        )
        with patch.dict(
            ext_mod._EXTENSION_TOKEN_REGISTRY,  # pylint: disable=protected-access
            {"test.cp.ok": class_ref},
            clear=False,
        ):
            with patch(
                "mugen.core.bootstrap.extensions.importlib.import_module",
                return_value=SimpleNamespace(DummyClass=_DummyCPExt),
            ):
                spec = ext_mod.resolve_extension_spec("test.cp.ok")
        self.assertEqual(spec.extension_type, "cp")
        self.assertIs(spec.interface, ICPExtension)
        self.assertIs(spec.extension_class, _DummyCPExt)

    async def test_default_registry_register_branches(self) -> None:
        messaging_service = SimpleNamespace(
            bind_cp_extension=lambda ext, **kwargs: None,
            register_cp_extension=lambda ext: None,
        )
        ipc_service = SimpleNamespace(bind_ipc_extension=lambda ext, **kwargs: None)
        platform_service = SimpleNamespace(extension_supported=lambda ext: True)
        logging_gateway = Mock()

        registry = ext_mod.DefaultExtensionRegistry(
            messaging_service=messaging_service,
            ipc_service=ipc_service,
            platform_service=platform_service,
            logging_gateway=logging_gateway,
        )

        with self.assertRaisesRegex(RuntimeError, "Unknown extension type"):
            await registry.register(
                app=object(),
                extension_type="unknown",
                extension=_DummyCPExt(),
                token="t",
                critical=False,
            )

        registry._platform_service = SimpleNamespace(extension_supported=lambda ext: False)  # pylint: disable=protected-access
        supported = await registry.register(
            app=object(),
            extension_type="cp",
            extension=_DummyCPExt(),
            token="tok",
            critical=False,
        )
        self.assertFalse(supported)

        registry._platform_service = SimpleNamespace(extension_supported=lambda ext: True)  # pylint: disable=protected-access
        fw = _DummyFWExt()
        fw.setup = AsyncMock(return_value=None)
        supported = await registry.register(
            app=object(),
            extension_type="fw",
            extension=fw,
            token="tok",
            critical=False,
        )
        self.assertTrue(supported)
        fw.setup.assert_awaited_once()

    async def test_default_registry_ipc_and_messaging_binding_fallbacks(self) -> None:
        # IPC bind fallback on TypeError.
        ipc_calls: list[tuple] = []

        def _ipc_bind_without_critical(ext):  # noqa: ANN001
            ipc_calls.append((ext,))

        registry = ext_mod.DefaultExtensionRegistry(
            messaging_service=SimpleNamespace(),
            ipc_service=SimpleNamespace(bind_ipc_extension=_ipc_bind_without_critical),
            platform_service=SimpleNamespace(extension_supported=lambda ext: True),
            logging_gateway=Mock(),
        )
        await registry.register(
            app=object(),
            extension_type="ipc",
            extension=_DummyIPCExt(),
            token="ipc.tok",
            critical=True,
        )
        self.assertEqual(len(ipc_calls), 1)

        # IPC register fallback branch.
        registered_ipc: list[object] = []
        registry = ext_mod.DefaultExtensionRegistry(
            messaging_service=SimpleNamespace(),
            ipc_service=SimpleNamespace(register_ipc_extension=lambda ext: registered_ipc.append(ext)),
            platform_service=SimpleNamespace(extension_supported=lambda ext: True),
            logging_gateway=Mock(),
        )
        await registry.register(
            app=object(),
            extension_type="ipc",
            extension=_DummyIPCExt(),
            token="ipc.tok",
            critical=False,
        )
        self.assertEqual(len(registered_ipc), 1)

        with self.assertRaisesRegex(RuntimeError, "IPC extension binding is unavailable"):
            registry = ext_mod.DefaultExtensionRegistry(
                messaging_service=SimpleNamespace(),
                ipc_service=SimpleNamespace(),
                platform_service=SimpleNamespace(extension_supported=lambda ext: True),
                logging_gateway=Mock(),
            )
            await registry.register(
                app=object(),
                extension_type="ipc",
                extension=_DummyIPCExt(),
                token="ipc.tok",
                critical=False,
            )

        # Messaging bind fallback on TypeError and register fallback.
        bind_calls: list[tuple] = []
        register_calls: list[object] = []

        def _bind_without_critical(ext):  # noqa: ANN001
            bind_calls.append((ext,))

        registry = ext_mod.DefaultExtensionRegistry(
            messaging_service=SimpleNamespace(bind_cp_extension=_bind_without_critical),
            ipc_service=SimpleNamespace(),
            platform_service=SimpleNamespace(extension_supported=lambda ext: True),
            logging_gateway=Mock(),
        )
        await registry.register(
            app=object(),
            extension_type="cp",
            extension=_DummyCPExt(),
            token="cp.tok",
            critical=True,
        )
        self.assertEqual(len(bind_calls), 1)

        registry = ext_mod.DefaultExtensionRegistry(
            messaging_service=SimpleNamespace(register_cp_extension=lambda ext: register_calls.append(ext)),
            ipc_service=SimpleNamespace(),
            platform_service=SimpleNamespace(extension_supported=lambda ext: True),
            logging_gateway=Mock(),
        )
        await registry.register(
            app=object(),
            extension_type="cp",
            extension=_DummyCPExt(),
            token="cp.tok",
            critical=False,
        )
        self.assertEqual(len(register_calls), 1)

        with self.assertRaisesRegex(RuntimeError, "Messaging extension binding is unavailable"):
            registry = ext_mod.DefaultExtensionRegistry(
                messaging_service=SimpleNamespace(),
                ipc_service=SimpleNamespace(),
                platform_service=SimpleNamespace(extension_supported=lambda ext: True),
                logging_gateway=Mock(),
            )
            await registry.register(
                app=object(),
                extension_type="cp",
                extension=_DummyCPExt(),
                token="cp.tok",
                critical=False,
            )

    async def test_default_registry_passes_critical_flag_to_bind_methods(self) -> None:
        ipc_calls: list[tuple[object, bool]] = []
        messaging_calls: list[tuple[object, bool]] = []

        def _bind_ipc(ext, *, critical: bool = False):  # noqa: ANN001
            ipc_calls.append((ext, critical))

        def _bind_cp(ext, *, critical: bool = False):  # noqa: ANN001
            messaging_calls.append((ext, critical))

        registry = ext_mod.DefaultExtensionRegistry(
            messaging_service=SimpleNamespace(bind_cp_extension=_bind_cp),
            ipc_service=SimpleNamespace(bind_ipc_extension=_bind_ipc),
            platform_service=SimpleNamespace(extension_supported=lambda ext: True),
            logging_gateway=Mock(),
        )

        await registry.register(
            app=object(),
            extension_type="ipc",
            extension=_DummyIPCExt(),
            token="ipc.tok",
            critical=True,
        )
        await registry.register(
            app=object(),
            extension_type="cp",
            extension=_DummyCPExt(),
            token="cp.tok",
            critical=True,
        )

        self.assertEqual(len(ipc_calls), 1)
        self.assertEqual(len(messaging_calls), 1)
        self.assertTrue(ipc_calls[0][1])
        self.assertTrue(messaging_calls[0][1])

    def test_configured_extensions_shape_validation(self) -> None:
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    core=SimpleNamespace(plugins=None),
                    extensions=None,
                )
            )
        )
        merged = ext_mod.configured_extensions(config)
        self.assertEqual(merged, [])

        bad_core = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    core=SimpleNamespace(plugins="bad"),
                )
            )
        )
        with self.assertRaisesRegex(RuntimeError, "core.plugins must be a list"):
            ext_mod.configured_extensions(bad_core)

        bad_ext = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    core=SimpleNamespace(plugins=[]),
                    extensions="bad",
                )
            )
        )
        with self.assertRaisesRegex(RuntimeError, "modules.extensions must be a list"):
            ext_mod.configured_extensions(bad_ext)


class TestProviderRegistryResolution(unittest.TestCase):
    def test_rejects_empty_token(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "must be non-empty"):
            provider_registry.resolve_provider_class(
                provider_name="completion_gateway",
                token="   ",
                interface=ICompletionGateway,
            )

    def test_import_or_shape_failure_raises_valid_subclass_not_found(self) -> None:
        with patch(
            "mugen.core.di.provider_registry.importlib.import_module",
            side_effect=ImportError("missing"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Valid subclass not found"):
                provider_registry.resolve_provider_class(
                    provider_name="completion_gateway",
                    token="deterministic",
                    interface=ICompletionGateway,
                )

        with patch(
            "mugen.core.di.provider_registry.importlib.import_module",
            return_value=SimpleNamespace(DeterministicCompletionGateway=object()),
        ):
            with self.assertRaisesRegex(RuntimeError, "Valid subclass not found"):
                provider_registry.resolve_provider_class(
                    provider_name="completion_gateway",
                    token="deterministic",
                    interface=ICompletionGateway,
                )

        with patch(
            "mugen.core.di.provider_registry.importlib.import_module",
            return_value=SimpleNamespace(
                DeterministicCompletionGateway=type("Wrong", (), {}),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "Valid subclass not found"):
                provider_registry.resolve_provider_class(
                    provider_name="completion_gateway",
                    token="deterministic",
                    interface=ICompletionGateway,
                )

    def test_successful_resolution_returns_provider_class(self) -> None:
        with patch(
            "mugen.core.di.provider_registry.importlib.import_module",
            return_value=SimpleNamespace(DeterministicCompletionGateway=_DummyCompletion),
        ):
            resolved = provider_registry.resolve_provider_class(
                provider_name="completion_gateway",
                token="deterministic",
                interface=ICompletionGateway,
            )
        self.assertIs(resolved, _DummyCompletion)

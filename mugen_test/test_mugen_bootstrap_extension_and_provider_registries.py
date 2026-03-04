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
from mugen.core.contract.gateway.knowledge import IKnowledgeGateway
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


class _DummyKnowledge(IKnowledgeGateway):
    async def check_readiness(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def search(self, params):  # noqa: ANN001
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
        with self.assertRaisesRegex(
            RuntimeError, "module:Class paths are not supported"
        ):
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
            ext_mod._CORE_EXTENSION_TOKEN_REGISTRY,  # pylint: disable=protected-access
            {"test.cp.dummy": class_ref},
            clear=False,
        ):
            with patch(
                "mugen.core.bootstrap.extensions.importlib.import_module",
                side_effect=ImportError("missing"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "Invalid extension class binding"
                ):
                    ext_mod.resolve_extension_spec("test.cp.dummy", scope="core")

            with patch(
                "mugen.core.bootstrap.extensions.importlib.import_module",
                return_value=SimpleNamespace(DummyClass=object()),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "Invalid extension class binding"
                ):
                    ext_mod.resolve_extension_spec("test.cp.dummy", scope="core")

            with patch(
                "mugen.core.bootstrap.extensions.importlib.import_module",
                return_value=SimpleNamespace(DummyClass=type("Wrong", (), {})),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "Invalid extension class binding"
                ):
                    ext_mod.resolve_extension_spec("test.cp.dummy", scope="core")

    def test_resolve_extension_spec_success(self) -> None:
        class_ref = ext_mod._ExtensionClassRef(  # pylint: disable=protected-access
            extension_type="cp",
            interface=ICPExtension,
            module_path="dummy.module",
            class_name="DummyClass",
        )
        with patch.dict(
            ext_mod._CORE_EXTENSION_TOKEN_REGISTRY,  # pylint: disable=protected-access
            {"test.cp.ok": class_ref},
            clear=False,
        ):
            with patch(
                "mugen.core.bootstrap.extensions.importlib.import_module",
                return_value=SimpleNamespace(DummyClass=_DummyCPExt),
            ):
                spec = ext_mod.resolve_extension_spec("test.cp.ok", scope="core")
        self.assertEqual(spec.extension_type, "cp")
        self.assertIs(spec.interface, ICPExtension)
        self.assertIs(spec.extension_class, _DummyCPExt)

    def test_parse_plugin_extension_class_ref_rejects_invalid_shape(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError, "Invalid plugin extension class binding"
        ):
            ext_mod._parse_plugin_extension_class_ref(  # pylint: disable=protected-access
                "plugin.cp.bad",
                ("cp", ICPExtension, "dummy.module"),
            )

    def test_plugin_extension_registry_returns_cached_value(self) -> None:
        cached_registry = {
            "plugin.cp.cached": ext_mod._ExtensionClassRef(  # pylint: disable=protected-access
                extension_type="cp",
                interface=ICPExtension,
                module_path="dummy.plugin",
                class_name="PluginCachedExt",
            )
        }
        with patch.object(
            ext_mod,
            "_PLUGIN_EXTENSION_TOKEN_REGISTRY_CACHE",
            cached_registry,
        ):
            resolved = (
                ext_mod._plugin_extension_token_registry()
            )  # pylint: disable=protected-access
        self.assertIs(resolved, cached_registry)

    def test_plugin_extension_registry_rejects_import_or_provider_shape(self) -> None:
        with patch.object(
            ext_mod, "_PLUGIN_EXTENSION_TOKEN_REGISTRY_CACHE", None
        ), patch(
            "mugen.core.bootstrap.extensions.importlib.import_module",
            side_effect=ImportError("missing"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Invalid plugin extension token registry configuration",
            ):
                ext_mod._plugin_extension_token_registry()  # pylint: disable=protected-access

        bad_provider_module = SimpleNamespace(
            **{
                ext_mod._PLUGIN_EXTENSION_REGISTRY_FUNC: object()
            }  # pylint: disable=protected-access
        )
        with patch.object(
            ext_mod, "_PLUGIN_EXTENSION_TOKEN_REGISTRY_CACHE", None
        ), patch(
            "mugen.core.bootstrap.extensions.importlib.import_module",
            return_value=bad_provider_module,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Invalid plugin extension token registry configuration",
            ):
                ext_mod._plugin_extension_token_registry()  # pylint: disable=protected-access

        bad_registry_module = SimpleNamespace(
            **{
                ext_mod._PLUGIN_EXTENSION_REGISTRY_FUNC: lambda: []
            }  # pylint: disable=protected-access
        )
        with patch.object(
            ext_mod, "_PLUGIN_EXTENSION_TOKEN_REGISTRY_CACHE", None
        ), patch(
            "mugen.core.bootstrap.extensions.importlib.import_module",
            return_value=bad_registry_module,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Invalid plugin extension token registry configuration",
            ):
                ext_mod._plugin_extension_token_registry()  # pylint: disable=protected-access

    def test_resolve_extension_spec_plugin_scope_and_invalid_scope(self) -> None:
        plugin_registry = {
            "plugin.cp.ok": ext_mod._ExtensionClassRef(  # pylint: disable=protected-access
                extension_type="cp",
                interface=ICPExtension,
                module_path="dummy.plugin",
                class_name="PluginCPExt",
            )
        }
        with patch(
            "mugen.core.bootstrap.extensions._plugin_extension_token_registry",
            return_value=plugin_registry,
        ), patch(
            "mugen.core.bootstrap.extensions.importlib.import_module",
            return_value=SimpleNamespace(PluginCPExt=_DummyCPExt),
        ):
            spec = ext_mod.resolve_extension_spec("plugin.cp.ok", scope="plugin")

        self.assertEqual(spec.extension_type, "cp")
        self.assertIs(spec.extension_class, _DummyCPExt)
        with self.assertRaisesRegex(RuntimeError, "Invalid extension token scope"):
            ext_mod.resolve_extension_spec("plugin.cp.ok", scope="legacy")

    async def test_default_registry_register_branches(self) -> None:
        messaging_service = SimpleNamespace(
            bind_cp_extension=lambda ext, **kwargs: None,
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

        registry._platform_service = SimpleNamespace(
            extension_supported=lambda ext: False
        )  # pylint: disable=protected-access
        supported = await registry.register(
            app=object(),
            extension_type="cp",
            extension=_DummyCPExt(),
            token="tok",
            critical=False,
        )
        self.assertFalse(supported)

        registry._platform_service = SimpleNamespace(
            extension_supported=lambda ext: True
        )  # pylint: disable=protected-access
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

    async def test_default_registry_requires_strict_bind_contracts(self) -> None:
        def _ipc_bind_without_critical(ext):  # noqa: ANN001
            _ = ext

        registry = ext_mod.DefaultExtensionRegistry(
            messaging_service=SimpleNamespace(),
            ipc_service=SimpleNamespace(bind_ipc_extension=_ipc_bind_without_critical),
            platform_service=SimpleNamespace(extension_supported=lambda ext: True),
            logging_gateway=Mock(),
        )
        with self.assertRaises(TypeError):
            await registry.register(
                app=object(),
                extension_type="ipc",
                extension=_DummyIPCExt(),
                token="ipc.tok",
                critical=True,
            )

        with self.assertRaisesRegex(AttributeError, "bind_ipc_extension"):
            registry = ext_mod.DefaultExtensionRegistry(
                messaging_service=SimpleNamespace(),
                ipc_service=SimpleNamespace(register_ipc_extension=lambda ext: ext),
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

        with self.assertRaisesRegex(AttributeError, "bind_cp_extension"):
            registry = ext_mod.DefaultExtensionRegistry(
                messaging_service=SimpleNamespace(
                    register_cp_extension=lambda ext: ext
                ),
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

    def test_bind_messaging_extension_dispatches_all_contract_methods(self) -> None:
        bind_calls: list[tuple[str, bool]] = []

        def _bind(kind: str):
            def _impl(_ext, *, critical: bool = False):  # noqa: ANN001
                bind_calls.append((kind, critical))

            return _impl

        registry = ext_mod.DefaultExtensionRegistry(
            messaging_service=SimpleNamespace(
                bind_cp_extension=_bind("cp"),
                bind_ct_extension=_bind("ct"),
                bind_ctx_extension=_bind("ctx"),
                bind_mh_extension=_bind("mh"),
                bind_rag_extension=_bind("rag"),
                bind_rpp_extension=_bind("rpp"),
            ),
            ipc_service=SimpleNamespace(
                bind_ipc_extension=lambda _ext, **_kwargs: None
            ),
            platform_service=SimpleNamespace(extension_supported=lambda ext: True),
            logging_gateway=Mock(),
        )

        for kind in ("ct", "ctx", "mh", "rag", "rpp"):
            registry._bind_messaging_extension(  # pylint: disable=protected-access
                extension_type=kind,
                extension=object(),
                critical=True,
            )

        self.assertEqual(
            bind_calls,
            [("ct", True), ("ctx", True), ("mh", True), ("rag", True), ("rpp", True)],
        )
        with self.assertRaisesRegex(RuntimeError, "binding is unavailable"):
            registry._bind_messaging_extension(  # pylint: disable=protected-access
                extension_type="unknown",
                extension=object(),
                critical=False,
            )

    def test_configured_extensions_shape_validation(self) -> None:
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    core=SimpleNamespace(extensions=None),
                    extensions=None,
                )
            )
        )
        merged = ext_mod.configured_extensions(config)
        self.assertEqual(merged, [])

        bad_core = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    core=SimpleNamespace(extensions="bad"),
                )
            )
        )
        with self.assertRaisesRegex(RuntimeError, "core.extensions must be a list"):
            ext_mod.configured_extensions(bad_core)

        bad_ext = SimpleNamespace(
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    core=SimpleNamespace(extensions=[]),
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
            return_value=SimpleNamespace(
                DeterministicCompletionGateway=_DummyCompletion
            ),
        ):
            resolved = provider_registry.resolve_provider_class(
                provider_name="completion_gateway",
                token="deterministic",
                interface=ICompletionGateway,
            )
        self.assertIs(resolved, _DummyCompletion)

    def test_vertex_completion_provider_token_resolves(self) -> None:
        with patch(
            "mugen.core.di.provider_registry.importlib.import_module",
            return_value=SimpleNamespace(VertexCompletionGateway=_DummyCompletion),
        ):
            resolved = provider_registry.resolve_provider_class(
                provider_name="completion_gateway",
                token="vertex",
                interface=ICompletionGateway,
            )
        self.assertIs(resolved, _DummyCompletion)

    def test_azure_foundry_completion_provider_token_resolves(self) -> None:
        with patch(
            "mugen.core.di.provider_registry.importlib.import_module",
            return_value=SimpleNamespace(AzureFoundryCompletionGateway=_DummyCompletion),
        ):
            resolved = provider_registry.resolve_provider_class(
                provider_name="completion_gateway",
                token="azure_foundry",
                interface=ICompletionGateway,
            )
        self.assertIs(resolved, _DummyCompletion)

    def test_cerebras_completion_provider_token_resolves(self) -> None:
        with patch(
            "mugen.core.di.provider_registry.importlib.import_module",
            return_value=SimpleNamespace(CerebrasCompletionGateway=_DummyCompletion),
        ):
            resolved = provider_registry.resolve_provider_class(
                provider_name="completion_gateway",
                token="cerebras",
                interface=ICompletionGateway,
            )
        self.assertIs(resolved, _DummyCompletion)

    def test_unknown_module_path_like_token_surfaces_token_guidance(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "must use provider tokens",
        ):
            provider_registry.resolve_provider_class(
                provider_name="completion_gateway",
                token="mugen.core.gateway.completion.bedrock",
                interface=ICompletionGateway,
            )

    def test_pgvector_knowledge_provider_token_resolves(self) -> None:
        with patch(
            "mugen.core.di.provider_registry.importlib.import_module",
            return_value=SimpleNamespace(PgVectorKnowledgeGateway=_DummyKnowledge),
        ):
            resolved = provider_registry.resolve_provider_class(
                provider_name="knowledge_gateway",
                token="pgvector",
                interface=IKnowledgeGateway,
            )
        self.assertIs(resolved, _DummyKnowledge)

    def test_chromadb_knowledge_provider_token_resolves(self) -> None:
        with patch(
            "mugen.core.di.provider_registry.importlib.import_module",
            return_value=SimpleNamespace(ChromaKnowledgeGateway=_DummyKnowledge),
        ):
            resolved = provider_registry.resolve_provider_class(
                provider_name="knowledge_gateway",
                token="chromadb",
                interface=IKnowledgeGateway,
            )
        self.assertIs(resolved, _DummyKnowledge)

    def test_milvus_knowledge_provider_token_resolves(self) -> None:
        with patch(
            "mugen.core.di.provider_registry.importlib.import_module",
            return_value=SimpleNamespace(MilvusKnowledgeGateway=_DummyKnowledge),
        ):
            resolved = provider_registry.resolve_provider_class(
                provider_name="knowledge_gateway",
                token="milvus",
                interface=IKnowledgeGateway,
            )
        self.assertIs(resolved, _DummyKnowledge)

    def test_pinecone_knowledge_provider_token_resolves(self) -> None:
        with patch(
            "mugen.core.di.provider_registry.importlib.import_module",
            return_value=SimpleNamespace(PineconeKnowledgeGateway=_DummyKnowledge),
        ):
            resolved = provider_registry.resolve_provider_class(
                provider_name="knowledge_gateway",
                token="pinecone",
                interface=IKnowledgeGateway,
            )
        self.assertIs(resolved, _DummyKnowledge)

    def test_weaviate_knowledge_provider_token_resolves(self) -> None:
        with patch(
            "mugen.core.di.provider_registry.importlib.import_module",
            return_value=SimpleNamespace(WeaviateKnowledgeGateway=_DummyKnowledge),
        ):
            resolved = provider_registry.resolve_provider_class(
                provider_name="knowledge_gateway",
                token="weaviate",
                interface=IKnowledgeGateway,
            )
        self.assertIs(resolved, _DummyKnowledge)

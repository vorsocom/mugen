"""Unit tests for tokenized extension registration."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from quart import Quart

import mugen as mugen_mod
from mugen import BootstrapConfigError, ExtensionLoadError, register_extensions


class _RegistryStub:
    def __init__(self, *, result: bool = True) -> None:
        self.calls: list[dict] = []
        self._result = result

    async def register(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self._result


def _base_cfg(
    core_extensions: list[SimpleNamespace],
    *,
    plugin_extensions: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        mugen=SimpleNamespace(
            modules=SimpleNamespace(
                core=SimpleNamespace(extensions=core_extensions),
                extensions=[] if plugin_extensions is None else plugin_extensions,
            )
        )
    )


class TestRegisterExtensions(unittest.IsolatedAsyncioTestCase):
    async def test_extension_enabled_parses_string_values(self) -> None:
        self.assertTrue(mugen_mod._extension_enabled(SimpleNamespace(enabled="yes")))  # pylint: disable=protected-access
        self.assertFalse(mugen_mod._extension_enabled(SimpleNamespace(enabled="off")))  # pylint: disable=protected-access
        self.assertTrue(mugen_mod._extension_enabled(SimpleNamespace(enabled="maybe")))  # pylint: disable=protected-access

    async def test_register_extensions_rejects_legacy_path_config(self) -> None:
        app = Quart("test_app")
        config = _base_cfg(
            [
                SimpleNamespace(
                    type="cp",
                    path="legacy.module:LegacyClass",
                )
            ]
        )
        with self.assertRaises(ExtensionLoadError):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_register_extensions_fails_for_critical_unknown_token(self) -> None:
        app = Quart("test_app")
        config = _base_cfg(
            [
                SimpleNamespace(
                    type="cp",
                    token="unknown.token",
                    critical=True,
                )
            ]
        )
        with self.assertRaises(ExtensionLoadError):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_register_extensions_ignores_noncritical_unknown_token(self) -> None:
        app = Quart("test_app")
        config = _base_cfg(
            [
                SimpleNamespace(
                    type="cp",
                    token="unknown.token",
                    critical=False,
                )
            ]
        )
        await register_extensions(
            app=app,
            config_provider=lambda: config,
            logger_provider=lambda: app.logger,
        )

    async def test_register_extensions_skips_disabled_entries(self) -> None:
        app = Quart("test_app")
        config = _base_cfg(
            [
                SimpleNamespace(
                    type="cp",
                    token="core.cp.clear_history",
                    enabled=False,
                )
            ]
        )
        registry = _RegistryStub()
        await register_extensions(
            app=app,
            config_provider=lambda: config,
            logger_provider=lambda: app.logger,
            extension_registry_provider=lambda: registry,
        )
        self.assertEqual(registry.calls, [])

    async def test_register_extensions_passes_resolved_type_and_token_to_registry(self) -> None:
        app = Quart("test_app")
        config = _base_cfg(
            [
                SimpleNamespace(
                    type="cp",
                    token="core.cp.clear_history",
                    critical=True,
                )
            ]
        )
        registry = _RegistryStub(result=True)
        await register_extensions(
            app=app,
            config_provider=lambda: config,
            logger_provider=lambda: app.logger,
            extension_registry_provider=lambda: registry,
        )
        self.assertEqual(len(registry.calls), 1)
        self.assertEqual(registry.calls[0]["extension_type"], "cp")
        self.assertEqual(registry.calls[0]["token"], "core.cp.clear_history")
        self.assertTrue(registry.calls[0]["critical"])

    async def test_register_extensions_rejects_type_token_mismatch_when_critical(self) -> None:
        app = Quart("test_app")
        config = _base_cfg(
            [
                SimpleNamespace(
                    type="mh",
                    token="core.cp.clear_history",
                    critical=True,
                )
            ]
        )
        with self.assertRaises(ExtensionLoadError):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_register_extensions_wraps_invalid_extension_schema(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(mugen=SimpleNamespace(modules=SimpleNamespace(extensions="bad")))
        with self.assertRaises(BootstrapConfigError):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                logger_provider=lambda: app.logger,
            )

    async def test_register_extensions_returns_grouped_registered_tokens(self) -> None:
        app = Quart("test_app")
        config = _base_cfg(
            [
                SimpleNamespace(type="cp", token="core.cp.clear_history"),
                SimpleNamespace(type="cp", token="core.cp.clear_history"),
            ]
        )
        registry = _RegistryStub(result=True)

        report = await register_extensions(
            app=app,
            config_provider=lambda: config,
            logger_provider=lambda: app.logger,
            extension_registry_provider=lambda: registry,
        )

        self.assertEqual(report, {"cp": ["core.cp.clear_history"]})

    async def test_build_core_extension_instance_supports_varargs_kwargs(self) -> None:
        class _CoreExtWithVarArgs:  # pylint: disable=too-few-public-methods
            def __init__(self, config, *args, **kwargs):  # noqa: ANN001
                self.config = config
                self.args = args
                self.kwargs = kwargs

        config = SimpleNamespace(marker="ok")
        ext = mugen_mod._build_core_extension_instance(  # pylint: disable=protected-access
            extension_class=_CoreExtWithVarArgs,
            config=config,
            keyval_storage_gateway_provider=lambda: object(),
        )
        self.assertIs(ext.config, config)
        self.assertEqual(ext.args, ())
        self.assertEqual(ext.kwargs, {})

    async def test_build_core_extension_instance_rejects_unsupported_dependency(self) -> None:
        class _CoreExtUnsupported:  # pylint: disable=too-few-public-methods
            def __init__(self, unsupported_dep):  # noqa: ANN001
                self.unsupported_dep = unsupported_dep

        with self.assertRaisesRegex(ExtensionLoadError, "constructor dependency is unsupported"):
            mugen_mod._build_core_extension_instance(  # pylint: disable=protected-access
                extension_class=_CoreExtUnsupported,
                config=SimpleNamespace(),
                keyval_storage_gateway_provider=lambda: object(),
            )

    async def test_build_core_extension_instance_allows_optional_unknown_dependency(self) -> None:
        class _CoreExtOptionalUnknown:  # pylint: disable=too-few-public-methods
            def __init__(self, config, optional_unknown="default"):  # noqa: ANN001
                self.config = config
                self.optional_unknown = optional_unknown

        config = SimpleNamespace(marker="ok")
        ext = mugen_mod._build_core_extension_instance(  # pylint: disable=protected-access
            extension_class=_CoreExtOptionalUnknown,
            config=config,
            keyval_storage_gateway_provider=lambda: object(),
        )
        self.assertIs(ext.config, config)
        self.assertEqual(ext.optional_unknown, "default")

"""Unit tests for tokenized extension registration."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from quart import Quart

import mugen as mugen_mod
from mugen.core.bootstrap.extensions import ExtensionTokenSpec
from mugen.core.contract.extension.cp import ICPExtension
from mugen.core.contract.extension.fw import IFWExtension
from mugen import BootstrapConfigError, ExtensionLoadError, register_extensions


class _RegistryStub:
    def __init__(self, *, result: bool = True) -> None:
        self.calls: list[dict] = []
        self._result = result

    async def register(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self._result


class _DummyCPExt(ICPExtension):
    @property
    def platforms(self) -> list[str]:
        return []

    @property
    def commands(self) -> list[str]:
        return ["clear"]

    async def process_message(self, message: str, room_id: str, user_id: str):
        _ = (message, room_id, user_id)
        return None


class _DummyFWExt(IFWExtension):
    @property
    def platforms(self) -> list[str]:
        return []

    async def setup(self, app):  # noqa: ANN001
        _ = app
        return None


def _provider_kwargs(app: Quart) -> dict[str, object]:
    return {
        "ipc_provider": lambda: SimpleNamespace(),
        "logger_provider": lambda: app.logger,
        "messaging_provider": lambda: SimpleNamespace(),
        "platform_provider": lambda: SimpleNamespace(),
    }


def _base_cfg(
    extensions: list[SimpleNamespace],
    *,
    legacy_core_extensions: object | None = None,
    legacy_core_plugins: object | None = None,
) -> SimpleNamespace:
    core = SimpleNamespace()
    if legacy_core_extensions is not None:
        core.extensions = legacy_core_extensions
    if legacy_core_plugins is not None:
        core.plugins = legacy_core_plugins
    return SimpleNamespace(
        mugen=SimpleNamespace(
            modules=SimpleNamespace(
                core=core,
                extensions=extensions,
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
                **_provider_kwargs(app),
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
                **_provider_kwargs(app),
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
            **_provider_kwargs(app),
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
            **_provider_kwargs(app),
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
        with patch(
            "mugen.resolve_configured_extension_spec",
            return_value=ExtensionTokenSpec("cp", ICPExtension, _DummyCPExt),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                **_provider_kwargs(app),
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
                **_provider_kwargs(app),
            )

    async def test_register_extensions_wraps_invalid_extension_schema(self) -> None:
        app = Quart("test_app")
        config = SimpleNamespace(mugen=SimpleNamespace(modules=SimpleNamespace(extensions="bad")))
        with self.assertRaises(BootstrapConfigError):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                **_provider_kwargs(app),
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

        with patch(
            "mugen.resolve_configured_extension_spec",
            return_value=ExtensionTokenSpec("cp", ICPExtension, _DummyCPExt),
        ):
            report = await register_extensions(
                app=app,
                config_provider=lambda: config,
                **_provider_kwargs(app),
                extension_registry_provider=lambda: registry,
            )

        self.assertEqual(report, {"cp": ["core.cp.clear_history"]})

    async def test_register_extensions_allows_unknown_downstream_fw_with_acp_metadata(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _base_cfg(
            [
                SimpleNamespace(type="fw", token="core.fw.acp"),
                SimpleNamespace(
                    type="fw",
                    token="vorsocom.fw.car_rentals",
                    name="com.vorsocomputing.mugen.car_rentals",
                    namespace="com.vorsocomputing.mugen.car_rentals",
                    contrib="plugins.car_rentals.contrib",
                ),
            ]
        )
        registry = _RegistryStub(result=True)

        def _resolve(token: object, *, scope: str = "any") -> ExtensionTokenSpec:
            _ = scope
            if token == "core.fw.acp":
                return ExtensionTokenSpec("fw", IFWExtension, _DummyFWExt)
            raise RuntimeError(
                f"Unknown extension token: {token!r}. Known tokens: core.fw.acp."
            )

        with patch(
            "mugen.core.bootstrap.extensions.resolve_extension_spec",
            side_effect=_resolve,
        ):
            report = await register_extensions(
                app=app,
                config_provider=lambda: config,
                **_provider_kwargs(app),
                extension_registry_provider=lambda: registry,
            )

        self.assertEqual(
            report,
            {"fw": ["core.fw.acp", "vorsocom.fw.car_rentals"]},
        )
        self.assertEqual(len(registry.calls), 2)
        self.assertEqual(registry.calls[1]["extension_type"], "fw")
        self.assertEqual(registry.calls[1]["token"], "vorsocom.fw.car_rentals")

    async def test_register_extensions_rejects_unknown_downstream_fw_missing_acp_metadata(
        self,
    ) -> None:
        app = Quart("test_app")
        config = _base_cfg(
            [
                SimpleNamespace(type="fw", token="core.fw.acp"),
                SimpleNamespace(
                    type="fw",
                    token="vorsocom.fw.car_rentals",
                    name="com.vorsocomputing.mugen.car_rentals",
                    namespace="com.vorsocomputing.mugen.car_rentals",
                    critical=False,
                ),
            ]
        )

        def _resolve(token: object, *, scope: str = "any") -> ExtensionTokenSpec:
            _ = scope
            if token == "core.fw.acp":
                return ExtensionTokenSpec("fw", IFWExtension, _DummyFWExt)
            raise RuntimeError(
                f"Unknown extension token: {token!r}. Known tokens: core.fw.acp."
            )

        with (
            patch(
                "mugen.core.bootstrap.extensions.resolve_extension_spec",
                side_effect=_resolve,
            ),
            self.assertRaisesRegex(
                ExtensionLoadError,
                "requires non-empty ACP metadata field\\(s\\): contrib",
            ),
        ):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                **_provider_kwargs(app),
            )

    async def test_register_extensions_fails_for_critical_unknown_ipc_token(self) -> None:
        app = Quart("test_app")
        config = _base_cfg(
            [
                SimpleNamespace(
                    type="ipc",
                    token="unknown.ipc",
                    critical=True,
                )
            ]
        )
        with self.assertRaises(ExtensionLoadError):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                **_provider_kwargs(app),
            )

    async def test_register_extensions_rejects_removed_core_extensions_key(self) -> None:
        app = Quart("test_app")
        config = _base_cfg(
            [],
            legacy_core_extensions=[SimpleNamespace(type="cp", token="core.cp.clear_history")],
        )
        with self.assertRaises(BootstrapConfigError):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                **_provider_kwargs(app),
            )

    async def test_register_extensions_rejects_removed_core_plugins_key(self) -> None:
        app = Quart("test_app")
        config = _base_cfg([], legacy_core_plugins=[])
        with self.assertRaises(BootstrapConfigError):
            await register_extensions(
                app=app,
                config_provider=lambda: config,
                **_provider_kwargs(app),
            )

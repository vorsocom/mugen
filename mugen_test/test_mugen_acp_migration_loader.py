"""Regression tests for ACP migration contributor discovery."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mugen.core.plugin.acp.migration import loader


def _fw_entry(
    *,
    token: str,
    name: str,
    namespace: str,
    contrib: str,
    enabled: bool = True,
) -> dict:
    return {
        "type": "fw",
        "token": token,
        "enabled": enabled,
        "name": name,
        "namespace": namespace,
        "contrib": contrib,
    }


def _cfg(*, core: list[dict] | None = None, ext: list[dict] | None = None) -> dict:
    return {
        "mugen": {
            "modules": {
                "core": {"extensions": list(core or [])},
                "extensions": list(ext or []),
            }
        },
        "acp": {"plugin_name": "com.vorsocomputing.mugen.acp"},
    }


class TestAcpMigrationLoader(unittest.TestCase):
    """Covers duplicate-collapse and conflict detection for FW plugin specs."""

    def test_plugin_identity_uses_name_fallback_and_requires_identity(self) -> None:
        self.assertEqual(
            loader._plugin_identity({"name": "com.vorsocomputing.mugen.acp"}),  # pylint: disable=protected-access
            "com.vorsocomputing.mugen.acp",
        )
        with self.assertRaises(KeyError):
            loader._plugin_identity({})  # pylint: disable=protected-access

    def test_import_callable_returns_contribute_and_rejects_non_callable(self) -> None:
        module = SimpleNamespace(contribute=lambda *_args, **_kwargs: None)
        with patch.object(loader, "import_module", return_value=module):
            fn = loader._import_callable("demo.contrib")  # pylint: disable=protected-access

        self.assertTrue(callable(fn))

        bad_module = SimpleNamespace(contribute="not-callable")
        with (
            patch.object(loader, "import_module", return_value=bad_module),
            self.assertRaisesRegex(TypeError, "demo.bad is not callable"),
        ):
            loader._import_callable("demo.bad")  # pylint: disable=protected-access

    def test_load_enabled_framework_plugins_skips_disabled_and_non_fw_entries(self) -> None:
        cfg = _cfg(
            core=[
                _fw_entry(
                    token="core.fw.acp",
                    name="com.vorsocomputing.mugen.acp",
                    namespace="com.vorsocomputing.mugen.acp",
                    contrib="mugen.core.plugin.acp.contrib",
                    enabled=False,
                ),
                {
                    "type": "cp",
                    "token": "core.cp.clear_history",
                    "enabled": True,
                    "name": "cp.clear_history",
                    "namespace": "cp.clear_history",
                    "contrib": "ignore.me",
                },
            ],
        )

        plugins = loader._load_enabled_framework_plugins(cfg)  # pylint: disable=protected-access

        self.assertEqual(plugins, [])

    def test_load_enabled_framework_plugins_collapses_identical_duplicates(self) -> None:
        cfg = _cfg(
            core=[
                _fw_entry(
                    token="core.fw.acp",
                    name="com.vorsocomputing.mugen.acp",
                    namespace="com.vorsocomputing.mugen.acp",
                    contrib="mugen.core.plugin.acp.contrib",
                )
            ],
            ext=[
                _fw_entry(
                    token="core.fw.acp",
                    name="com.vorsocomputing.mugen.acp",
                    namespace="com.vorsocomputing.mugen.acp",
                    contrib="mugen.core.plugin.acp.contrib",
                )
            ],
        )

        plugins = loader._load_enabled_framework_plugins(cfg)  # pylint: disable=protected-access

        self.assertEqual(len(plugins), 1)
        self.assertEqual(plugins[0].token, "core.fw.acp")

    def test_load_enabled_framework_plugins_rejects_conflicting_duplicates(self) -> None:
        cfg = _cfg(
            core=[
                _fw_entry(
                    token="core.fw.acp",
                    name="com.vorsocomputing.mugen.acp",
                    namespace="com.vorsocomputing.mugen.acp",
                    contrib="mugen.core.plugin.acp.contrib",
                )
            ],
            ext=[
                _fw_entry(
                    token="core.fw.acp",
                    name="com.vorsocomputing.mugen.acp",
                    namespace="com.vorsocomputing.mugen.acp",
                    contrib="mugen.core.plugin.acp.contrib.alt",
                )
            ],
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "Conflicting framework plugin configuration",
        ):
            loader._load_enabled_framework_plugins(cfg)  # pylint: disable=protected-access

    def test_contribute_all_uses_collapsed_admin_plugin_once(self) -> None:
        cfg = _cfg(
            core=[
                _fw_entry(
                    token="core.fw.acp",
                    name="com.vorsocomputing.mugen.acp",
                    namespace="com.vorsocomputing.mugen.acp",
                    contrib="mugen.core.plugin.acp.contrib",
                )
            ],
            ext=[
                _fw_entry(
                    token="core.fw.acp",
                    name="com.vorsocomputing.mugen.acp",
                    namespace="com.vorsocomputing.mugen.acp",
                    contrib="mugen.core.plugin.acp.contrib",
                ),
                _fw_entry(
                    token="core.fw.audit",
                    name="com.vorsocomputing.mugen.audit",
                    namespace="com.vorsocomputing.mugen.audit",
                    contrib="mugen.core.plugin.audit.contrib",
                ),
            ],
        )
        registry = object()
        acp_fn = Mock()
        audit_fn = Mock()

        with patch.object(loader, "_import_callable", side_effect=[acp_fn, audit_fn]):
            loader.contribute_all(registry, mugen_cfg=cfg)

        acp_fn.assert_called_once_with(
            registry,
            admin_namespace="com.vorsocomputing.mugen.acp",
            plugin_namespace="com.vorsocomputing.mugen.acp",
        )
        audit_fn.assert_called_once_with(
            registry,
            admin_namespace="com.vorsocomputing.mugen.acp",
            plugin_namespace="com.vorsocomputing.mugen.audit",
        )

    def test_contribute_all_requires_admin_plugin(self) -> None:
        cfg = _cfg(
            ext=[
                _fw_entry(
                    token="core.fw.audit",
                    name="com.vorsocomputing.mugen.audit",
                    namespace="com.vorsocomputing.mugen.audit",
                    contrib="mugen.core.plugin.audit.contrib",
                )
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "admin plugin is required"):
            loader.contribute_all(object(), mugen_cfg=cfg)

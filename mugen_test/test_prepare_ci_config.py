"""Regression tests for deterministic CI config preparation."""

from __future__ import annotations

import runpy
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import tomlkit

import scripts.prepare_ci_config as prepare_ci_config


def _load_sample_doc():
    return tomlkit.parse(Path("conf/mugen.toml.sample").read_text(encoding="utf-8"))


def _args(*, sample: Path, output: Path, enable_web_platform: bool) -> SimpleNamespace:
    return SimpleNamespace(
        sample=str(sample),
        output=str(output),
        rdbms_url="postgresql+psycopg://mugen:mugen@127.0.0.1:5432/mugen",
        aws_region="us-east-1",
        admin_password="aDmin,123",
        jwt_kid="ci-ed25519",
        jwt_issuer="mugen-ci",
        jwt_audience="mugen-ci",
        acp_secret_key="ci-acp-secret-key",
        acp_managed_secret_encryption_key="ci-acp-managed-secret-root-key-0123456789",
        refresh_token_pepper="ci-refresh-pepper",
        quart_secret_key="ci-quart-secret-key-0123456789abcdef",
        web_media_storage_path=".tmp/ci/web_media",
        web_media_object_cache_path=".tmp/ci/web_media_object_cache",
        enable_web_platform=enable_web_platform,
    )


class TestPrepareCiConfig(unittest.TestCase):
    """Ensure CI config generation stays deduplicated and deterministic."""

    def test_generate_ed25519_private_pem_returns_private_key_pem(self) -> None:
        pem = prepare_ci_config._generate_ed25519_private_pem()  # pylint: disable=protected-access

        self.assertTrue(pem.startswith("-----BEGIN PRIVATE KEY-----"))
        self.assertTrue(pem.strip().endswith("-----END PRIVATE KEY-----"))

    def test_parse_args_uses_defaults(self) -> None:
        with patch.object(sys, "argv", ["prepare_ci_config.py"]):
            args = prepare_ci_config._parse_args()  # pylint: disable=protected-access

        self.assertEqual(args.sample, "conf/mugen.toml.sample")
        self.assertEqual(args.output, "mugen.toml")
        self.assertEqual(args.aws_region, "us-east-1")
        self.assertEqual(
            args.acp_managed_secret_encryption_key,
            "ci-acp-managed-secret-root-key-0123456789",
        )
        self.assertFalse(args.enable_web_platform)

    def test_ensure_platform_enabled_appends_only_once(self) -> None:
        doc = tomlkit.parse('[mugen]\nplatforms = ["matrix"]\n')

        prepare_ci_config._ensure_platform_enabled(  # pylint: disable=protected-access
            doc,
            "web",
        )
        prepare_ci_config._ensure_platform_enabled(  # pylint: disable=protected-access
            doc,
            "web",
        )

        self.assertEqual([str(item) for item in doc["mugen"]["platforms"]], ["matrix", "web"])

    def test_ensure_framework_extension_repairs_sections_and_deduplicates_matches(
        self,
    ) -> None:
        doc = _load_sample_doc()
        doc["mugen"]["modules"]["core"]["extensions"] = "broken"
        doc["mugen"]["modules"]["extensions"] = tomlkit.aot()

        duplicate = tomlkit.table()
        duplicate["type"] = "fw"
        duplicate["token"] = "core.fw.context_engine"
        duplicate["enabled"] = True
        duplicate["name"] = "duplicate"
        duplicate["namespace"] = "duplicate"
        duplicate["models"] = "duplicate.module"
        duplicate["contrib"] = "duplicate.contrib"
        doc["mugen"]["modules"]["extensions"].append(duplicate)

        prepare_ci_config._ensure_framework_extension(  # pylint: disable=protected-access
            doc,
            token="core.fw.context_engine",
            name="com.vorsocomputing.mugen.context_engine",
            namespace="com.vorsocomputing.mugen.context_engine",
            models="",
            contrib="mugen.core.plugin.context_engine.contrib",
        )

        plugins = doc["mugen"]["modules"]["core"]["extensions"] + doc["mugen"][
            "modules"
        ]["extensions"]
        matches = [
            plugin for plugin in plugins if plugin.get("token") == "core.fw.context_engine"
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["contrib"], "mugen.core.plugin.context_engine.contrib")
        self.assertNotIn("models", matches[0])
        self.assertEqual(
            len(
                [
                    plugin
                    for plugin in doc["mugen"]["modules"]["core"]["extensions"]
                    if plugin.get("token") == "core.fw.context_engine"
                ]
            ),
            0,
        )
        self.assertEqual(
            len(
                [
                    plugin
                    for plugin in doc["mugen"]["modules"]["extensions"]
                    if plugin.get("token") == "core.fw.context_engine"
                ]
            ),
            1,
        )

    def test_ensure_framework_extension_prunes_duplicate_matches_across_sections(
        self,
    ) -> None:
        doc = _load_sample_doc()
        if "extensions" not in doc["mugen"]["modules"] or not isinstance(
            doc["mugen"]["modules"].get("extensions"), list
        ):
            doc["mugen"]["modules"]["extensions"] = tomlkit.aot()

        duplicate = tomlkit.table()
        duplicate["type"] = "fw"
        duplicate["token"] = "core.fw.acp"
        duplicate["enabled"] = True
        duplicate["name"] = "com.vorsocomputing.mugen.acp"
        duplicate["namespace"] = "com.vorsocomputing.mugen.acp"
        duplicate["models"] = "mugen.core.plugin.acp.model"
        duplicate["contrib"] = "mugen.core.plugin.acp.contrib"
        doc["mugen"]["modules"]["extensions"].append(duplicate)

        prepare_ci_config._ensure_framework_extension(  # pylint: disable=protected-access
            doc,
            token="core.fw.acp",
            name="com.vorsocomputing.mugen.acp",
            namespace="com.vorsocomputing.mugen.acp",
            models="mugen.core.plugin.acp.model",
            contrib="mugen.core.plugin.acp.contrib",
        )

        plugins = doc["mugen"]["modules"]["core"].get("extensions", []) + doc["mugen"][
            "modules"
        ].get("extensions", [])
        self.assertEqual(
            len([plugin for plugin in plugins if plugin.get("token") == "core.fw.acp"]),
            1,
        )
        self.assertEqual(
            len(
                [
                    plugin
                    for plugin in doc["mugen"]["modules"]["core"].get("extensions", [])
                    if plugin.get("token") == "core.fw.acp"
                ]
            ),
            0,
        )
        self.assertEqual(
            len(
                [
                    plugin
                    for plugin in doc["mugen"]["modules"].get("extensions", [])
                    if plugin.get("token") == "core.fw.acp"
                ]
            ),
            1,
        )

    def test_ensure_framework_extension_moves_core_only_fw_entry_to_plugin_section(
        self,
    ) -> None:
        doc = tomlkit.parse(
            """
[mugen]
[mugen.modules]
[mugen.modules.core]
[[mugen.modules.core.extensions]]
type = "fw"
token = "core.fw.web"
enabled = true
name = "legacy.web"
namespace = "legacy.web"
contrib = "legacy.web.contrib"
"""
        )

        prepare_ci_config._ensure_framework_extension(  # pylint: disable=protected-access
            doc,
            token="core.fw.web",
            name="com.vorsocomputing.mugen.web",
            namespace="com.vorsocomputing.mugen.web",
            models="mugen.core.plugin.web.model",
            contrib="mugen.core.plugin.web.contrib",
        )

        self.assertEqual(
            len(doc["mugen"]["modules"]["core"].get("extensions", [])),
            0,
        )
        self.assertEqual(
            len(doc["mugen"]["modules"].get("extensions", [])),
            1,
        )
        plugin_entry = doc["mugen"]["modules"]["extensions"][0]
        self.assertEqual(plugin_entry["token"], "core.fw.web")
        self.assertEqual(plugin_entry["name"], "com.vorsocomputing.mugen.web")
        self.assertEqual(plugin_entry["namespace"], "com.vorsocomputing.mugen.web")
        self.assertEqual(plugin_entry["models"], "mugen.core.plugin.web.model")
        self.assertEqual(plugin_entry["contrib"], "mugen.core.plugin.web.contrib")

    def test_ensure_framework_extension_appends_without_models_when_missing(self) -> None:
        doc = tomlkit.parse("[mugen]\n[mugen.modules]\n[mugen.modules.core]\n")

        prepare_ci_config._ensure_framework_extension(  # pylint: disable=protected-access
            doc,
            token="core.fw.context_engine",
            name="com.vorsocomputing.mugen.context_engine",
            namespace="com.vorsocomputing.mugen.context_engine",
            models="",
            contrib="mugen.core.plugin.context_engine.contrib",
        )

        appended = doc["mugen"]["modules"]["extensions"][0]
        self.assertEqual(appended["token"], "core.fw.context_engine")
        self.assertNotIn("models", appended)

    def test_enable_ci_framework_plugins_updates_existing_fw_entries_without_duplicates(
        self,
    ) -> None:
        doc = _load_sample_doc()

        prepare_ci_config._enable_ci_framework_plugins(doc)  # pylint: disable=protected-access

        plugins = doc["mugen"]["modules"]["core"].get("extensions", []) + doc["mugen"][
            "modules"
        ].get("extensions", [])
        fw_plugins = [
            plugin
            for plugin in plugins
            if str(plugin.get("type", "")).strip().lower() == "fw"
        ]

        self.assertEqual(
            len(
                [
                    plugin
                    for plugin in fw_plugins
                    if plugin.get("token") == "core.fw.acp"
                ]
            ),
            1,
        )
        self.assertEqual(
            len(
                [
                    plugin
                    for plugin in fw_plugins
                    if plugin.get("token") == "core.fw.web"
                ]
            ),
            1,
        )
        self.assertEqual(
            len(
                [
                    plugin
                    for plugin in fw_plugins
                    if plugin.get("token") == "core.fw.context_engine"
                ]
            ),
            1,
        )
        self.assertEqual(
            len(
                [
                    plugin
                    for plugin in fw_plugins
                    if plugin.get("token") == "core.fw.audit"
                ]
            ),
            1,
        )
        self.assertEqual(
            len(
                [
                    plugin
                    for plugin in doc["mugen"]["modules"]["core"].get("extensions", [])
                    if str(plugin.get("type", "")).strip().lower() == "fw"
                ]
            ),
            0,
        )

    def test_main_writes_ci_config_without_web_platform_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sample = Path(tmpdir) / "sample.toml"
            output = Path(tmpdir) / "rendered.toml"
            sample_text = Path("conf/mugen.toml.sample").read_text(encoding="utf-8")
            sample.write_text(sample_text)
            original = tomlkit.parse(sample_text)

            with (
                patch.object(
                    prepare_ci_config,
                    "_parse_args",
                    return_value=_args(
                        sample=sample,
                        output=output,
                        enable_web_platform=False,
                    ),
                ),
                patch.object(
                    prepare_ci_config,
                    "_generate_ed25519_private_pem",
                    return_value="PEM",
                ),
                patch.object(
                    prepare_ci_config,
                    "generate_password_hash",
                    side_effect=lambda value: f"hash::{value}",
                ),
            ):
                self.assertEqual(prepare_ci_config.main(), 0)

            rendered = tomlkit.parse(output.read_text(encoding="utf-8"))
            self.assertEqual(
                rendered["mugen"]["modules"]["core"]["gateway"]["completion"],
                "deterministic",
            )
            self.assertEqual(
                rendered["mugen"]["modules"]["core"]["service"]["ingress"],
                "default",
            )
            self.assertEqual(
                [str(item) for item in rendered["mugen"]["platforms"]],
                [str(item) for item in original["mugen"]["platforms"]],
            )
            self.assertEqual(rendered["acp"]["jwt"]["keys"][0]["pem"], "PEM")
            self.assertEqual(
                len(
                    [
                        plugin
                        for plugin in rendered["mugen"]["modules"]["core"]["extensions"]
                        if str(plugin.get("type", "")).strip().lower() == "fw"
                    ]
                ),
                0,
            )
            self.assertEqual(
                rendered["acp"]["key_management"]["providers"]["managed"][
                    "encryption_key"
                ],
                "ci-acp-managed-secret-root-key-0123456789",
            )

    def test_main_writes_ci_config_with_web_platform_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sample = Path(tmpdir) / "sample.toml"
            output = Path(tmpdir) / "rendered.toml"
            sample.write_text(Path("conf/mugen.toml.sample").read_text(encoding="utf-8"))

            with (
                patch.object(
                    prepare_ci_config,
                    "_parse_args",
                    return_value=_args(
                        sample=sample,
                        output=output,
                        enable_web_platform=True,
                    ),
                ),
                patch.object(
                    prepare_ci_config,
                    "_generate_ed25519_private_pem",
                    return_value="PEM",
                ),
                patch.object(
                    prepare_ci_config,
                    "generate_password_hash",
                    side_effect=lambda value: f"hash::{value}",
                ),
            ):
                self.assertEqual(prepare_ci_config.main(), 0)

            rendered = tomlkit.parse(output.read_text(encoding="utf-8"))
            self.assertIn("web", [str(item) for item in rendered["mugen"]["platforms"]])
            self.assertEqual(
                rendered["mugen"]["modules"]["core"]["service"]["ingress"],
                "default",
            )
            self.assertEqual(
                rendered["web"]["media"]["storage"]["path"],
                ".tmp/ci/web_media",
            )
            self.assertEqual(
                rendered["web"]["media"]["object"]["cache_path"],
                ".tmp/ci/web_media_object_cache",
            )
            self.assertEqual(
                len(
                    [
                        plugin
                        for plugin in rendered["mugen"]["modules"]["core"]["extensions"]
                        if str(plugin.get("type", "")).strip().lower() == "fw"
                    ]
                ),
                0,
            )
            self.assertEqual(
                len(
                    [
                        plugin
                        for plugin in rendered["mugen"]["modules"]["extensions"]
                        if plugin.get("token") == "core.fw.acp"
                    ]
                ),
                1,
            )
            self.assertEqual(
                rendered["acp"]["key_management"]["providers"]["managed"][
                    "encryption_key"
                ],
                "ci-acp-managed-secret-root-key-0123456789",
            )
            self.assertEqual(
                len(
                    [
                        plugin
                        for plugin in rendered["mugen"]["modules"]["extensions"]
                        if plugin.get("token") == "core.fw.web"
                    ]
                ),
                1,
            )

    def test_module_entrypoint_runs_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sample = Path(tmpdir) / "sample.toml"
            output = Path(tmpdir) / "rendered.toml"
            sample.write_text(Path("conf/mugen.toml.sample").read_text(encoding="utf-8"))

            with patch.object(
                sys,
                "argv",
                [
                    "scripts/prepare_ci_config.py",
                    "--sample",
                    str(sample),
                    "--output",
                    str(output),
                ],
            ):
                with self.assertRaises(SystemExit) as exc:
                    runpy.run_path(
                        "scripts/prepare_ci_config.py",
                        run_name="__main__",
                    )

            self.assertEqual(exc.exception.code, 0)
            self.assertTrue(output.exists())

"""Unit tests for migration config contract helpers."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from mugen.core.contract import migration_config


class TestMigrationConfigContract(unittest.TestCase):
    """Exercise migration config helper branches for strict coverage gates."""

    def test_resolve_path_prefers_cli_over_env_and_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.dict(
                "os.environ",
                {"MUGEN_CONFIG_FILE": "from-env.toml"},
                clear=False,
            ):
                resolved = migration_config.resolve_mugen_config_path(
                    "from-cli.toml",
                    repo_root=root,
                )
        self.assertEqual(resolved, (root / "from-cli.toml").resolve())

    def test_resolve_path_uses_env_when_cli_is_blank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.dict(
                "os.environ",
                {"MUGEN_CONFIG_FILE": "from-env.toml"},
                clear=False,
            ):
                resolved = migration_config.resolve_mugen_config_path(
                    "   ",
                    repo_root=root,
                )
        self.assertEqual(resolved, (root / "from-env.toml").resolve())

    def test_resolve_path_uses_default_when_cli_and_env_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.dict("os.environ", {}, clear=True):
                resolved = migration_config.resolve_mugen_config_path(
                    None,
                    repo_root=root,
                )
        self.assertEqual(
            resolved,
            (root / migration_config.DEFAULT_MUGEN_CONFIG_FILE).resolve(),
        )

    def test_resolve_path_preserves_absolute_cli_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "absolute.toml"
            resolved = migration_config.resolve_mugen_config_path(str(config_file))
        self.assertEqual(resolved, config_file.resolve())

    def test_load_mugen_config_reads_valid_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "mugen.toml"
            config_file.write_text("[rdbms]\n", encoding="utf-8")
            loaded = migration_config.load_mugen_config(config_file)
        self.assertEqual(loaded, {"rdbms": {}})

    def test_load_mugen_config_raises_for_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.toml"
            with self.assertRaisesRegex(RuntimeError, "Config file not found"):
                migration_config.load_mugen_config(missing)

    def test_load_mugen_config_raises_for_permission_denied(self) -> None:
        with mock.patch("pathlib.Path.open", side_effect=PermissionError):
            with self.assertRaisesRegex(RuntimeError, "Config file is not readable"):
                migration_config.load_mugen_config(Path("mugen.toml"))

    def test_load_mugen_config_raises_for_invalid_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "mugen.toml"
            config_file.write_text("not=valid==", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "Config file is not valid TOML"):
                migration_config.load_mugen_config(config_file)

    def test_load_mugen_config_raises_when_toml_root_is_not_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "mugen.toml"
            config_file.write_text("[root]\nvalue = 1\n", encoding="utf-8")
            with mock.patch.object(migration_config.tomllib, "load", return_value=[]):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "Config file must parse to a TOML table",
                ):
                    migration_config.load_mugen_config(config_file)

    def test_core_extension_entries_returns_empty_when_modules_not_mapping(self) -> None:
        self.assertEqual(
            migration_config.configured_core_extension_entries(
                {"mugen": {"modules": []}}
            ),
            [],
        )

    def test_core_extension_entries_returns_empty_when_core_not_mapping(self) -> None:
        self.assertEqual(
            migration_config.configured_core_extension_entries(
                {"mugen": {"modules": {"core": []}}}
            ),
            [],
        )

    def test_core_extension_entries_rejects_legacy_plugins_key(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "core.plugins is no longer supported"):
            migration_config.configured_core_extension_entries(
                {"mugen": {"modules": {"core": {"plugins": []}}}}
            )

    def test_core_extension_entries_allows_none_as_empty(self) -> None:
        self.assertEqual(
            migration_config.configured_core_extension_entries(
                {"mugen": {"modules": {"core": {"extensions": None}}}}
            ),
            [],
        )

    def test_core_extension_entries_rejects_non_list(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "core.extensions must be an array"):
            migration_config.configured_core_extension_entries(
                {"mugen": {"modules": {"core": {"extensions": {}}}}}
            )

    def test_core_extension_entries_rejects_non_table_rows(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "core.extensions\\[0\\] must be a table",
        ):
            migration_config.configured_core_extension_entries(
                {"mugen": {"modules": {"core": {"extensions": ["bad"]}}}}
            )

    def test_core_extension_entries_returns_rows(self) -> None:
        entries = [{"models": "core.model"}]
        self.assertEqual(
            migration_config.configured_core_extension_entries(
                {"mugen": {"modules": {"core": {"extensions": entries}}}}
            ),
            entries,
        )

    def test_downstream_extension_entries_returns_empty_when_modules_not_mapping(self) -> None:
        self.assertEqual(
            migration_config.configured_downstream_extension_entries(
                {"mugen": {"modules": []}}
            ),
            [],
        )

    def test_downstream_extension_entries_allows_none_as_empty(self) -> None:
        self.assertEqual(
            migration_config.configured_downstream_extension_entries(
                {"mugen": {"modules": {"extensions": None}}}
            ),
            [],
        )

    def test_downstream_extension_entries_rejects_non_list(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "modules.extensions must be an array"):
            migration_config.configured_downstream_extension_entries(
                {"mugen": {"modules": {"extensions": {}}}}
            )

    def test_downstream_extension_entries_rejects_non_table_rows(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "modules.extensions\\[0\\] must be a table",
        ):
            migration_config.configured_downstream_extension_entries(
                {"mugen": {"modules": {"extensions": ["bad"]}}}
            )

    def test_downstream_extension_entries_returns_rows(self) -> None:
        entries = [{"models": "downstream.model"}]
        self.assertEqual(
            migration_config.configured_downstream_extension_entries(
                {"mugen": {"modules": {"extensions": entries}}}
            ),
            entries,
        )

    def test_migration_schema_bootstrap_order_handles_equal_schemas(self) -> None:
        self.assertEqual(
            migration_config.migration_schema_bootstrap_order(
                runtime_schema="mugen",
                version_table_schema="mugen",
            ),
            ("mugen",),
        )

    def test_migration_schema_bootstrap_order_handles_distinct_schemas(self) -> None:
        self.assertEqual(
            migration_config.migration_schema_bootstrap_order(
                runtime_schema="mugen",
                version_table_schema="mugen_versions",
            ),
            ("mugen", "mugen_versions"),
        )


if __name__ == "__main__":
    unittest.main()

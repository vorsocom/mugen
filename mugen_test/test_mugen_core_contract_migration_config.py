"""Unit tests for migration config contract helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
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

    def test_extension_entries_returns_empty_when_modules_not_mapping(self) -> None:
        self.assertEqual(
            migration_config.configured_extension_entries(
                {"mugen": {"modules": []}}
            ),
            [],
        )

    def test_extension_entries_ignores_non_mapping_core_config(self) -> None:
        entries = [{"models": "downstream.model"}]
        self.assertEqual(
            migration_config.configured_extension_entries(
                {"mugen": {"modules": {"core": [], "extensions": entries}}}
            ),
            entries,
        )

    def test_extension_entries_rejects_legacy_plugins_key(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "core.plugins is no longer supported"):
            migration_config.configured_extension_entries(
                {"mugen": {"modules": {"core": {"plugins": []}}}}
            )

    def test_extension_entries_rejects_legacy_extensions_key(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "core.extensions is no longer supported",
        ):
            migration_config.configured_extension_entries(
                {"mugen": {"modules": {"core": {"extensions": []}}}}
            )

    def test_extension_entries_allows_none_as_empty(self) -> None:
        self.assertEqual(
            migration_config.configured_extension_entries(
                {"mugen": {"modules": {"extensions": None}}}
            ),
            [],
        )

    def test_extension_entries_rejects_non_list(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "modules.extensions must be an array"):
            migration_config.configured_extension_entries(
                {"mugen": {"modules": {"extensions": {}}}}
            )

    def test_extension_entries_rejects_non_table_rows(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "modules.extensions\\[0\\] must be a table",
        ):
            migration_config.configured_extension_entries(
                {"mugen": {"modules": {"extensions": ["bad"]}}}
            )

    def test_extension_entries_returns_rows(self) -> None:
        entries = [{"models": "downstream.model"}]
        self.assertEqual(
            migration_config.configured_extension_entries(
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

    def test_private_path_and_model_module_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(
                migration_config._resolve_path("alembic.ini", root),
                (root / "alembic.ini").resolve(),
            )
            absolute = root / "absolute.ini"
            self.assertEqual(
                migration_config._resolve_path(str(absolute), root),
                absolute.resolve(),
            )

        self.assertEqual(migration_config._normalize_model_modules(None, "core"), ())
        self.assertEqual(
            migration_config._normalize_model_modules(
                [" alpha.beta ", "", "gamma.delta"],
                "core",
            ),
            ("alpha.beta", "gamma.delta"),
        )
        with self.assertRaisesRegex(RuntimeError, "invalid model_modules"):
            migration_config._normalize_model_modules("bad", "core")
        with self.assertRaisesRegex(RuntimeError, "non-string model_modules entry"):
            migration_config._normalize_model_modules(["ok", 1], "core")

    def test_build_track_spec_applies_defaults_and_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            spec = migration_config._build_track_spec(
                name="ctx-plugin",
                raw={
                    "enabled": False,
                    "version_table_schema": "ctx_versions",
                    "model_modules": ["ctx.model"],
                },
                repo_root=repo_root,
                defaults={
                    "alembic_config": "plugins/ctx-plugin/alembic.ini",
                    "schema": "ctx_runtime",
                    "version_table": "ctx_version",
                },
            )

        self.assertEqual(spec.name, "ctx-plugin")
        self.assertFalse(spec.enabled)
        self.assertEqual(
            spec.alembic_config,
            (repo_root / "plugins/ctx-plugin/alembic.ini").resolve(),
        )
        self.assertEqual(spec.schema_raw, "ctx_runtime")
        self.assertEqual(spec.version_table_raw, "ctx_version")
        self.assertEqual(spec.version_table_schema_raw, "ctx_versions")
        self.assertEqual(spec.model_modules_raw, ["ctx.model"])

    def test_load_track_specs_validates_structure_and_builds_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            cfg = {
                "rdbms": {
                    "migration_tracks": {
                        "core": {
                            "schema": "core_runtime",
                            "alembic_config": "core/alembic.ini",
                        },
                        "plugins": [
                            {
                                "name": "ctx-plugin",
                                "enabled": False,
                                "model_modules": ["ctx.model", ""],
                            }
                        ],
                    }
                }
            }

            specs = migration_config.load_track_specs(cfg, repo_root)

        self.assertEqual([spec.name for spec in specs], ["core", "ctx-plugin"])
        self.assertEqual(specs[0].schema_raw, "core_runtime")
        self.assertEqual(
            specs[1].alembic_config,
            (repo_root / "plugins/ctx-plugin/alembic.ini").resolve(),
        )
        self.assertEqual(specs[1].schema_raw, "plugin_ctx_plugin")
        self.assertEqual(specs[1].version_table_raw, "alembic_version")
        self.assertEqual(specs[1].version_table_schema_raw, "plugin_ctx_plugin")
        self.assertEqual(specs[1].model_modules_raw, ["ctx.model", ""])

        with self.assertRaisesRegex(RuntimeError, "migration_tracks must be a table"):
            migration_config.load_track_specs(
                {"rdbms": {"migration_tracks": [1]}},
                Path.cwd(),
            )
        with self.assertRaisesRegex(RuntimeError, "migration_tracks.core must be a table"):
            migration_config.load_track_specs(
                {
                    "rdbms": {
                        "migration_tracks": {
                            "core": SimpleNamespace(schema="core_runtime"),
                        }
                    }
                },
                Path.cwd(),
            )
        with self.assertRaisesRegex(
            RuntimeError,
            "migration_tracks.plugins must be an array of tables",
        ):
            migration_config.load_track_specs(
                {
                    "rdbms": {
                        "migration_tracks": {
                            "core": {"schema": "core_runtime"},
                            "plugins": {"bad": True},
                        }
                    }
                },
                Path.cwd(),
            )
        with self.assertRaisesRegex(RuntimeError, "plugin entry must be a table"):
            migration_config.load_track_specs(
                {
                    "rdbms": {
                        "migration_tracks": {
                            "core": {"schema": "core_runtime"},
                            "plugins": ["bad"],
                        }
                    }
                },
                Path.cwd(),
            )
        with self.assertRaisesRegex(RuntimeError, "requires a non-empty 'name'"):
            migration_config.load_track_specs(
                {
                    "rdbms": {
                        "migration_tracks": {
                            "core": {"schema": "core_runtime"},
                            "plugins": [{}],
                        }
                    }
                },
                Path.cwd(),
            )
        with self.assertRaisesRegex(
            RuntimeError,
            "Duplicate migration track names detected",
        ):
            migration_config.load_track_specs(
                {
                    "rdbms": {
                        "migration_tracks": {
                            "core": {"schema": "core_runtime"},
                            "plugins": [{"name": "core"}],
                        }
                    }
                },
                Path.cwd(),
            )

    def test_select_track_specs_covers_selection_modes(self) -> None:
        track_specs = [
            migration_config.MigrationTrackSpec(
                name="core",
                enabled=True,
                alembic_config=Path("alembic.ini"),
                schema_raw="core_runtime",
                version_table_raw="alembic_version",
                version_table_schema_raw="core_runtime",
            ),
            migration_config.MigrationTrackSpec(
                name="ctx-plugin",
                enabled=False,
                alembic_config=Path("plugins/ctx-plugin/alembic.ini"),
                schema_raw="ctx_runtime",
                version_table_raw="alembic_version",
                version_table_schema_raw="ctx_runtime",
            ),
        ]

        self.assertEqual(
            [
                track.name
                for track in migration_config.select_track_specs(
                    track_specs,
                    selected_names=[],
                    include_disabled=False,
                )
            ],
            ["core"],
        )
        self.assertEqual(
            [
                track.name
                for track in migration_config.select_track_specs(
                    track_specs,
                    selected_names=["ctx-plugin"],
                    include_disabled=True,
                )
            ],
            ["ctx-plugin"],
        )

        with self.assertRaisesRegex(RuntimeError, "Unknown migration track\\(s\\): missing"):
            migration_config.select_track_specs(
                track_specs,
                selected_names=["missing"],
                include_disabled=False,
            )
        with self.assertRaisesRegex(
            RuntimeError,
            "Selected migration track\\(s\\) are disabled",
        ):
            migration_config.select_track_specs(
                track_specs,
                selected_names=["ctx-plugin"],
                include_disabled=False,
            )
        with self.assertRaisesRegex(
            RuntimeError,
            "No migration tracks selected for execution",
        ):
            migration_config.select_track_specs(
                [
                    migration_config.MigrationTrackSpec(
                        name="disabled",
                        enabled=False,
                        alembic_config=Path("alembic.ini"),
                        schema_raw="core_runtime",
                        version_table_raw="alembic_version",
                        version_table_schema_raw="core_runtime",
                    )
                ],
                selected_names=[],
                include_disabled=False,
            )

    def test_select_track_specs_covers_enabled_selected_branch_and_empty_effective_guard(
        self,
    ) -> None:
        track_specs = [
            migration_config.MigrationTrackSpec(
                name="core",
                enabled=True,
                alembic_config=Path("alembic.ini"),
                schema_raw="core_runtime",
                version_table_raw="alembic_version",
                version_table_schema_raw="core_runtime",
            )
        ]
        self.assertEqual(
            [
                track.name
                for track in migration_config.select_track_specs(
                    track_specs,
                    selected_names=["core"],
                    include_disabled=False,
                )
            ],
            ["core"],
        )

        class _FlakyTrack:
            def __init__(self) -> None:
                self.name = "core"
                self._enabled_reads = 0

            @property
            def enabled(self) -> bool:
                self._enabled_reads += 1
                return self._enabled_reads == 1

        with self.assertRaisesRegex(
            RuntimeError,
            "No effective migration tracks selected from --track options",
        ):
            migration_config.select_track_specs(
                [_FlakyTrack()],
                selected_names=["core"],
                include_disabled=False,
            )

    def test_materialize_execution_tracks_validates_paths_and_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            alembic_config = repo_root / "alembic.ini"
            alembic_config.write_text("[alembic]\n", encoding="utf-8")

            tracks = migration_config.materialize_execution_tracks(
                [
                    migration_config.MigrationTrackSpec(
                        name="core",
                        enabled=True,
                        alembic_config=alembic_config,
                        schema_raw="core_runtime",
                        version_table_raw="alembic_version",
                        version_table_schema_raw="core_runtime",
                        model_modules_raw=[" core.model ", ""],
                    )
                ],
                core_schema="core_runtime",
            )

        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].name, "core")
        self.assertEqual(tracks[0].schema, "core_runtime")
        self.assertEqual(tracks[0].version_table, "alembic_version")
        self.assertEqual(tracks[0].version_table_schema, "core_runtime")
        self.assertEqual(tracks[0].model_modules, ("core.model",))
        self.assertEqual(tracks[0].core_schema, "core_runtime")

        with self.assertRaisesRegex(RuntimeError, "Alembic config not found"):
            migration_config.materialize_execution_tracks(
                [
                    migration_config.MigrationTrackSpec(
                        name="broken",
                        enabled=True,
                        alembic_config=Path("/does/not/exist.ini"),
                        schema_raw="core_runtime",
                        version_table_raw="alembic_version",
                        version_table_schema_raw="core_runtime",
                    )
                ],
                core_schema="core_runtime",
            )
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            alembic_config = repo_root / "alembic.ini"
            alembic_config.write_text("[alembic]\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "version_table for track 'broken'"):
                migration_config.materialize_execution_tracks(
                    [
                        migration_config.MigrationTrackSpec(
                            name="broken",
                            enabled=True,
                            alembic_config=alembic_config,
                            schema_raw="core_runtime",
                            version_table_raw="bad-table",
                            version_table_schema_raw="core_runtime",
                        )
                    ],
                    core_schema="core_runtime",
                )
            with self.assertRaisesRegex(
                RuntimeError,
                "version_table_schema for track 'broken'",
            ):
                migration_config.materialize_execution_tracks(
                    [
                        migration_config.MigrationTrackSpec(
                            name="broken",
                            enabled=True,
                            alembic_config=alembic_config,
                            schema_raw="core_runtime",
                            version_table_raw="alembic_version",
                            version_table_schema_raw="bad-schema",
                        )
                    ],
                    core_schema="core_runtime",
                )


if __name__ == "__main__":
    unittest.main()

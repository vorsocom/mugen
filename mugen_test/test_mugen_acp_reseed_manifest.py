"""Tests for ACP manifest reseed command behavior."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from mugen.core.plugin.acp.migration import reseed_manifest

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _minimal_config() -> str:
    return """
[mugen]
environment = "development"

[mugen.modules]
extensions = []

[rdbms.alembic]
url = "postgresql+psycopg://old:old@old/old"

[rdbms.sqlalchemy]
url = "postgresql+psycopg://old:old@old/old"

[rdbms.migration_tracks.core]
schema = "mugen"
""".strip()


class _ScalarResult:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value


class _FakeConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement, params=None):  # noqa: ANN001, ANN201 - SQLAlchemy shim
        self.statements.append(str(statement))
        return _ScalarResult(3 if params and "plugin_namespace" in params else 0)


class _FakeBegin:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> _FakeConnection:
        return self.connection

    def __exit__(self, exc_type, exc, traceback) -> bool:  # noqa: ANN001
        return False


class _FakeEngine:
    def __init__(self) -> None:
        self.connection = _FakeConnection()

    def begin(self) -> _FakeBegin:
        return _FakeBegin(self.connection)


class TestAcpReseedManifest(unittest.TestCase):
    """Covers env-aware ACP seed manifest reseeding."""

    def test_build_manifest_uses_enabled_extension_metadata(self) -> None:
        manifest = reseed_manifest._build_manifest(
            {
                "mugen": {
                    "modules": {
                        "extensions": [
                            {
                                "type": "fw",
                                "token": "core.fw.acp",
                                "enabled": True,
                                "name": "com.vorsocomputing.mugen.acp",
                                "namespace": "com.vorsocomputing.mugen.acp",
                                "contrib": "mugen.core.plugin.acp.contrib",
                            },
                            {
                                "type": "fw",
                                "token": "core.fw.knowledge_pack",
                                "enabled": True,
                                "name": (
                                    "com.vorsocomputing.mugen.knowledge_pack"
                                ),
                                "namespace": (
                                    "com.vorsocomputing.mugen.knowledge_pack"
                                ),
                                "contrib": (
                                    "mugen.core.plugin.knowledge_pack.contrib"
                                ),
                            },
                        ]
                    }
                }
            }
        )

        self.assertTrue(
            any(
                item.namespace == "com.vorsocomputing.mugen.knowledge_pack"
                for item in manifest.permission_objects
            )
        )

    def test_cli_dry_run_uses_deployment_overlay_for_enabled_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mugen.toml"
            config_path.write_text(_minimal_config(), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "mugen.core.plugin.acp.migration.reseed_manifest",
                    "--config",
                    str(config_path),
                    "--plugin-namespace",
                    "com.vorsocomputing.mugen.knowledge_pack",
                    "--dry-run",
                ],
                cwd=_REPO_ROOT,
                env={
                    "HOME": os.environ.get("HOME", ""),
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONPATH": str(_REPO_ROOT),
                    "MUGEN_ENABLED_EXTENSIONS": (
                        "core.fw.acp,core.fw.knowledge_pack"
                    ),
                    "MUGEN_CONFIG_OVERLAY_JSON": json.dumps(
                        {
                            "rdbms": {
                                "migration_tracks": {
                                    "core": {
                                        "schema": "mugen_overlay",
                                    }
                                }
                            }
                        }
                    ),
                },
                capture_output=True,
                check=False,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DRY_RUN: no DB changes applied", result.stdout)
        self.assertIn("manifest.plugin_permission_objects=", result.stdout)
        self.assertNotIn("manifest.plugin_permission_objects=0", result.stdout)
        self.assertIn("manifest.plugin_default_global_grants=", result.stdout)
        self.assertNotIn("manifest.plugin_default_global_grants=0", result.stdout)

    def test_reseed_manifest_applies_to_configured_core_schema(self) -> None:
        fake_engine = _FakeEngine()
        fake_manifest = SimpleNamespace(
            permission_objects=[object(), object()],
            permission_types=[object()],
            global_roles=[object()],
            default_global_grants=[object(), object(), object()],
        )
        config = {
            "mugen": {
                "modules": {
                    "extensions": [
                        {
                            "type": "fw",
                            "token": "core.fw.acp",
                            "enabled": True,
                            "name": "com.vorsocomputing.mugen.acp",
                            "namespace": "com.vorsocomputing.mugen.acp",
                            "contrib": "mugen.core.plugin.acp.contrib",
                        }
                    ]
                }
            },
            "rdbms": {
                "alembic": {
                    "url": "postgresql+psycopg://mugen:mugen@db/mugen",
                },
                "migration_tracks": {
                    "core": {
                        "schema": "custom_schema",
                    }
                },
            },
        }

        stdout = io.StringIO()
        apply_manifest = mock.Mock()
        with (
            mock.patch.object(
                reseed_manifest,
                "_build_manifest",
                return_value=fake_manifest,
            ),
            mock.patch.object(
                reseed_manifest,
                "create_engine",
                return_value=fake_engine,
            ),
            mock.patch.object(
                reseed_manifest.importlib,
                "import_module",
                return_value=SimpleNamespace(apply_manifest=apply_manifest),
            ),
            contextlib.redirect_stdout(stdout),
        ):
            code = reseed_manifest.reseed_manifest(
                mugen_cfg=config,
                schema=None,
                plugin_namespace="com.vorsocomputing.mugen.acp",
                dry_run=False,
            )

        self.assertEqual(code, 0)
        apply_manifest.assert_called_once_with(
            fake_engine.connection,
            fake_manifest,
            schema="custom_schema",
        )
        self.assertTrue(
            any(
                "SET search_path TO custom_schema, public" in statement
                for statement in fake_engine.connection.statements
            )
        )
        self.assertIn("APPLY_MANIFEST_OK", stdout.getvalue())
        self.assertIn("db.plugin_permission_objects=3", stdout.getvalue())
        self.assertIn("db.plugin_admin_grants=3", stdout.getvalue())

    def test_reseed_manifest_dry_run_without_plugin_namespace(self) -> None:
        fake_manifest = SimpleNamespace(
            permission_objects=[],
            permission_types=[],
            global_roles=[],
            default_global_grants=[],
        )

        stdout = io.StringIO()
        with (
            mock.patch.object(
                reseed_manifest,
                "_build_manifest",
                return_value=fake_manifest,
            ),
            contextlib.redirect_stdout(stdout),
        ):
            code = reseed_manifest.reseed_manifest(
                mugen_cfg={
                    "rdbms": {
                        "migration_tracks": {
                            "core": {
                                "schema": "mugen",
                            }
                        }
                    }
                },
                schema="override_schema",
                plugin_namespace=None,
                dry_run=True,
            )

        self.assertEqual(code, 0)
        self.assertIn("manifest.permission_objects=0", stdout.getvalue())
        self.assertNotIn("manifest.plugin_permission_objects", stdout.getvalue())

    def test_reseed_manifest_dry_run_with_plugin_namespace_counts_manifest(self) -> None:
        fake_manifest = SimpleNamespace(
            permission_objects=[
                SimpleNamespace(namespace="com.example.plugin"),
                SimpleNamespace(namespace="com.example.other"),
            ],
            permission_types=[],
            global_roles=[],
            default_global_grants=[
                SimpleNamespace(permission_object="com.example.plugin:thing"),
                SimpleNamespace(permission_object="com.example.other:thing"),
            ],
        )

        stdout = io.StringIO()
        with (
            mock.patch.object(
                reseed_manifest,
                "_build_manifest",
                return_value=fake_manifest,
            ),
            contextlib.redirect_stdout(stdout),
        ):
            code = reseed_manifest.reseed_manifest(
                mugen_cfg={
                    "rdbms": {
                        "migration_tracks": {
                            "core": {
                                "schema": "mugen",
                            }
                        }
                    }
                },
                schema=None,
                plugin_namespace="com.example.plugin",
                dry_run=True,
            )

        self.assertEqual(code, 0)
        self.assertIn("manifest.plugin_permission_objects=1", stdout.getvalue())
        self.assertIn("manifest.plugin_default_global_grants=1", stdout.getvalue())

    def test_reseed_manifest_applies_without_plugin_namespace(self) -> None:
        fake_engine = _FakeEngine()
        fake_manifest = SimpleNamespace(
            permission_objects=[],
            permission_types=[],
            global_roles=[],
            default_global_grants=[],
        )
        config = {
            "mugen": {
                "modules": {
                    "extensions": [
                        {
                            "type": "fw",
                            "token": "core.fw.acp",
                            "enabled": True,
                            "name": "com.vorsocomputing.mugen.acp",
                            "namespace": "com.vorsocomputing.mugen.acp",
                            "contrib": "mugen.core.plugin.acp.contrib",
                        }
                    ]
                }
            },
            "rdbms": {
                "alembic": {
                    "url": "postgresql+psycopg://mugen:mugen@db/mugen",
                },
                "migration_tracks": {
                    "core": {
                        "schema": "custom_schema",
                    }
                },
            },
        }

        stdout = io.StringIO()
        apply_manifest = mock.Mock()
        with (
            mock.patch.object(
                reseed_manifest,
                "_build_manifest",
                return_value=fake_manifest,
            ),
            mock.patch.object(
                reseed_manifest,
                "create_engine",
                return_value=fake_engine,
            ),
            mock.patch.object(
                reseed_manifest.importlib,
                "import_module",
                return_value=SimpleNamespace(apply_manifest=apply_manifest),
            ),
            contextlib.redirect_stdout(stdout),
        ):
            code = reseed_manifest.reseed_manifest(
                mugen_cfg=config,
                schema=None,
                plugin_namespace=None,
                dry_run=False,
            )

        self.assertEqual(code, 0)
        apply_manifest.assert_called_once_with(
            fake_engine.connection,
            fake_manifest,
            schema="custom_schema",
        )
        self.assertIn("APPLY_MANIFEST_OK", stdout.getvalue())
        self.assertNotIn("db.plugin_permission_objects", stdout.getvalue())

    def test_cli_reports_config_loading_errors(self) -> None:
        stdout = io.StringIO()
        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "reseed_manifest",
                    "--config",
                    "missing.toml",
                    "--dry-run",
                ],
            ),
            contextlib.redirect_stdout(stdout),
        ):
            code = reseed_manifest.main()

        self.assertEqual(code, 1)
        self.assertIn("Config file not found", stdout.getvalue())

    def test_main_loads_overlay_config_and_dispatches_reseed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mugen.toml"
            config_path.write_text(_minimal_config(), encoding="utf-8")

            with (
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "reseed_manifest",
                        "--config",
                        str(config_path),
                        "--schema",
                        "explicit_schema",
                        "--plugin-namespace",
                        "com.example.plugin",
                        "--dry-run",
                    ],
                ),
                mock.patch.object(
                    reseed_manifest,
                    "reseed_manifest",
                    return_value=0,
                ) as reseed,
            ):
                code = reseed_manifest.main()

        self.assertEqual(code, 0)
        kwargs = reseed.call_args.kwargs
        self.assertEqual(kwargs["schema"], "explicit_schema")
        self.assertEqual(kwargs["plugin_namespace"], "com.example.plugin")
        self.assertTrue(kwargs["dry_run"])
        self.assertEqual(
            kwargs["mugen_cfg"]["rdbms"]["migration_tracks"]["core"]["schema"],
            "mugen",
        )

    def test_validators_reject_invalid_schema_and_namespace(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid schema name"):
            reseed_manifest.reseed_manifest(
                mugen_cfg={
                    "rdbms": {
                        "migration_tracks": {
                            "core": {
                                "schema": "mugen",
                            }
                        }
                    }
                },
                schema="bad-schema",
                plugin_namespace=None,
                dry_run=True,
            )

        with self.assertRaisesRegex(ValueError, "Invalid plugin namespace"):
            reseed_manifest._validate_namespace(
                "bad-namespace",
                "plugin namespace",
            )


if __name__ == "__main__":
    unittest.main()

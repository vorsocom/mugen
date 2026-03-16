"""Unit tests for core utility config/security helpers."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from sqlalchemy import Column, ForeignKeyConstraint, Integer, MetaData, Table

from mugen.core.utility.rdbms_schema import (
    AGENT_RUNTIME_SCHEMA_TOKEN,
    CONTEXT_ENGINE_SCHEMA_TOKEN,
    CORE_SCHEMA_TOKEN,
    clone_metadata_with_schema_map,
    normalize_track_name,
    qualify_sql_name,
    resolve_core_rdbms_schema,
    resolve_plugin_track_schema,
    resolve_rdbms_schema_contract,
    schema_token_for_track,
    validate_sql_identifier,
)
from mugen.core.utility.security import (
    validate_matrix_secret_encryption_key,
    validate_quart_secret_key,
)


class TestMugenUtilityRdbmsSchema(unittest.TestCase):
    """Covers core schema contract helpers."""

    def test_validate_sql_identifier_accepts_valid_values(self) -> None:
        self.assertEqual(
            validate_sql_identifier("core_runtime", label="schema"),
            "core_runtime",
        )

    def test_validate_sql_identifier_rejects_invalid_values(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "expected SQL identifier string"):
            validate_sql_identifier(123, label="schema")
        with self.assertRaisesRegex(RuntimeError, "Invalid schema"):
            validate_sql_identifier("bad-schema", label="schema")

    def test_resolve_core_rdbms_schema_requires_explicit_value(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "rdbms.migration_tracks.core.schema is required",
        ):
            resolve_core_rdbms_schema({})
        with self.assertRaisesRegex(
            RuntimeError,
            "rdbms.migration_tracks.core.schema is required",
        ):
            resolve_core_rdbms_schema(
                {"rdbms": {"migration_tracks": {"core": {"schema": ""}}}}
            )

    def test_resolve_core_rdbms_schema_resolves_dict_value(self) -> None:
        self.assertEqual(
            resolve_core_rdbms_schema(
                {"rdbms": {"migration_tracks": {"core": {"schema": "core_runtime"}}}}
            ),
            "core_runtime",
        )

    def test_resolve_core_rdbms_schema_resolves_namespace_and_rejects_invalid(self) -> None:
        config = SimpleNamespace(
            rdbms=SimpleNamespace(
                migration_tracks=SimpleNamespace(
                    core=SimpleNamespace(schema="core_runtime"),
                )
            )
        )
        self.assertEqual(resolve_core_rdbms_schema(config), "core_runtime")
        with self.assertRaisesRegex(
            RuntimeError,
            "rdbms.migration_tracks.core.schema is required",
        ):
            resolve_core_rdbms_schema(SimpleNamespace(rdbms=None))
        with self.assertRaisesRegex(
            RuntimeError,
            "rdbms.migration_tracks.core.schema is required",
        ):
            resolve_core_rdbms_schema(
                SimpleNamespace(rdbms=SimpleNamespace())
            )

        with self.assertRaisesRegex(RuntimeError, "Invalid rdbms.migration_tracks.core.schema"):
            resolve_core_rdbms_schema(
                {"rdbms": {"migration_tracks": {"core": {"schema": "bad-schema"}}}}
            )

    def test_qualify_sql_name_validates_parts(self) -> None:
        self.assertEqual(
            qualify_sql_name(schema="core_runtime", name="core_keyval_entry"),
            "core_runtime.core_keyval_entry",
        )
        with self.assertRaisesRegex(RuntimeError, "Invalid name"):
            qualify_sql_name(schema="core_runtime", name="bad-name")

    def test_schema_token_for_track_returns_stable_tokens(self) -> None:
        self.assertEqual(schema_token_for_track("core"), CORE_SCHEMA_TOKEN)
        self.assertEqual(
            schema_token_for_track("context_engine"),
            CONTEXT_ENGINE_SCHEMA_TOKEN,
        )
        self.assertEqual(
            schema_token_for_track("agent_runtime"),
            AGENT_RUNTIME_SCHEMA_TOKEN,
        )
        self.assertEqual(
            schema_token_for_track("acme-extension"),
            "mugen_track_acme_extension",
        )

    def test_normalize_track_name_rejects_invalid_values(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "expected string"):
            normalize_track_name(123)
        with self.assertRaisesRegex(RuntimeError, "Invalid migration track name"):
            normalize_track_name("bad track")

    def test_resolve_rdbms_schema_contract_maps_builtin_plugin_tracks(self) -> None:
        contract = resolve_rdbms_schema_contract(
            {
                "rdbms": {
                    "migration_tracks": {
                        "core": {"schema": "core_runtime"},
                        "plugins": [
                            {"name": "context_engine", "schema": "ctx_runtime"},
                            {"name": "acme-extension", "schema": "acme_runtime"},
                        ],
                    }
                }
            }
        )

        self.assertEqual(contract.core_schema, "core_runtime")
        self.assertEqual(contract.schema_for_track("core"), "core_runtime")
        self.assertEqual(contract.schema_for_track("context_engine"), "ctx_runtime")
        self.assertEqual(contract.schema_for_track("agent_runtime"), "core_runtime")
        self.assertEqual(contract.schema_for_track("acme-extension"), "acme_runtime")
        self.assertEqual(contract.schema_translate_map[CORE_SCHEMA_TOKEN], "core_runtime")
        self.assertEqual(
            contract.schema_translate_map[CONTEXT_ENGINE_SCHEMA_TOKEN],
            "ctx_runtime",
        )
        self.assertEqual(
            contract.schema_translate_map[AGENT_RUNTIME_SCHEMA_TOKEN],
            "core_runtime",
        )
        self.assertEqual(contract.token_for_track("agent_runtime"), AGENT_RUNTIME_SCHEMA_TOKEN)
        self.assertEqual(
            contract.qualify(track_name="context_engine", name="context_profile"),
            "ctx_runtime.context_profile",
        )
        with self.assertRaisesRegex(RuntimeError, "Unknown migration track schema"):
            contract.schema_for_track("missing")

    def test_resolve_plugin_track_schema_covers_defaults_and_validation(self) -> None:
        self.assertEqual(
            resolve_plugin_track_schema(
                {
                    "rdbms": {
                        "migration_tracks": {
                            "core": {"schema": "core_runtime"},
                            "plugins": None,
                        }
                    }
                },
                track_name="ctx_plugin",
                default="fallback_schema",
            ),
            "fallback_schema",
        )
        self.assertEqual(
            resolve_plugin_track_schema(
                SimpleNamespace(
                    rdbms=SimpleNamespace(
                        migration_tracks=SimpleNamespace(
                            plugins=[
                                SimpleNamespace(
                                    name="ctx_plugin",
                                    schema="ctx_runtime",
                                )
                            ]
                        )
                    )
                ),
                track_name="ctx_plugin",
            ),
            "ctx_runtime",
        )
        self.assertEqual(
            resolve_plugin_track_schema(
                {
                    "rdbms": {
                        "migration_tracks": {
                            "plugins": [None],
                        }
                    }
                },
                track_name="ctx_plugin",
                default="fallback_schema",
            ),
            "fallback_schema",
        )
        self.assertEqual(
            resolve_plugin_track_schema(
                {
                    "rdbms": {
                        "migration_tracks": {
                            "plugins": [
                                {"name": "other_plugin", "schema": "other_runtime"},
                            ],
                        }
                    }
                },
                track_name="ctx_plugin",
                default="fallback_schema",
            ),
            "fallback_schema",
        )
        with self.assertRaisesRegex(RuntimeError, "plugins must be a list"):
            resolve_plugin_track_schema(
                {
                    "rdbms": {
                        "migration_tracks": {
                            "plugins": {},
                        }
                    }
                },
                track_name="ctx_plugin",
                default="fallback_schema",
            )
        with self.assertRaisesRegex(RuntimeError, "track 'ctx_plugin' is missing"):
            resolve_plugin_track_schema(
                {
                    "rdbms": {
                        "migration_tracks": {
                            "plugins": [{"name": "ctx_plugin"}],
                        }
                    }
                },
                track_name="ctx_plugin",
            )

    def test_resolve_rdbms_schema_contract_validates_plugin_entries(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "plugin entry requires name"):
            resolve_rdbms_schema_contract(
                {
                    "rdbms": {
                        "migration_tracks": {
                            "core": {"schema": "core_runtime"},
                            "plugins": [{}],
                        }
                    }
                }
            )
        with self.assertRaisesRegex(RuntimeError, "schema for track 'ctx_plugin' is required"):
            resolve_rdbms_schema_contract(
                {
                    "rdbms": {
                        "migration_tracks": {
                            "core": {"schema": "core_runtime"},
                            "plugins": [{"name": "ctx_plugin"}],
                        }
                    }
                }
            )

    def test_clone_metadata_with_schema_map_rewrites_table_and_fk_schemas(self) -> None:
        metadata = MetaData()
        Table(
            "admin_tenant",
            metadata,
            Column("id", Integer, primary_key=True),
            schema=CORE_SCHEMA_TOKEN,
        )
        child = Table(
            "context_item",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("tenant_id", Integer, nullable=False),
            ForeignKeyConstraint(
                ["tenant_id"],
                [f"{CORE_SCHEMA_TOKEN}.admin_tenant.id"],
            ),
            schema=CONTEXT_ENGINE_SCHEMA_TOKEN,
        )

        translated = clone_metadata_with_schema_map(
            metadata,
            schema_map={
                CORE_SCHEMA_TOKEN: "core_runtime",
                CONTEXT_ENGINE_SCHEMA_TOKEN: "ctx_runtime",
            },
        )

        translated_child = translated.tables["ctx_runtime.context_item"]
        self.assertEqual(translated_child.schema, "ctx_runtime")
        self.assertEqual(
            next(iter(translated_child.foreign_key_constraints)).elements[0].target_fullname,
            "core_runtime.admin_tenant.id",
        )
        self.assertEqual(child.schema, CONTEXT_ENGINE_SCHEMA_TOKEN)

    def test_clone_metadata_with_schema_map_keeps_none_schema_and_unqualified_fk(self) -> None:
        metadata = MetaData()
        Table(
            "unscoped_parent",
            metadata,
            Column("id", Integer, primary_key=True),
        )
        Table(
            "unscoped_child",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("parent_id", Integer, nullable=False),
            ForeignKeyConstraint(["parent_id"], ["unscoped_parent.id"]),
        )

        translated = clone_metadata_with_schema_map(
            metadata,
            schema_map={CORE_SCHEMA_TOKEN: "core_runtime"},
        )

        translated_child = translated.tables["unscoped_child"]
        self.assertIsNone(translated_child.schema)
        self.assertEqual(
            next(iter(translated_child.foreign_key_constraints)).elements[0].target_fullname,
            "unscoped_parent.id",
        )


class TestMugenUtilitySecurity(unittest.TestCase):
    """Covers Quart secret-key validation helper."""

    def test_validate_quart_secret_key_accepts_strong_value(self) -> None:
        secret = "0123456789abcdef0123456789abcdef"
        self.assertEqual(validate_quart_secret_key(secret), secret)

    def test_validate_quart_secret_key_rejects_invalid_values(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "must be a string"):
            validate_quart_secret_key(123)
        with self.assertRaisesRegex(RuntimeError, "must be non-empty"):
            validate_quart_secret_key("   ")
        with self.assertRaisesRegex(RuntimeError, "at least 32 characters"):
            validate_quart_secret_key("short")
        with self.assertRaisesRegex(RuntimeError, "must not use placeholder"):
            validate_quart_secret_key("changemechangemechangemechangeme")
        with self.assertRaisesRegex(RuntimeError, "must not use placeholder"):
            validate_quart_secret_key("<set-quart-secret-key-xxxxxxxxxxxxx>")
        with self.assertRaisesRegex(RuntimeError, "must not use placeholder"):
            validate_quart_secret_key("<aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa>")

    def test_validate_matrix_secret_encryption_key_accepts_strong_value(self) -> None:
        secret = "0123456789abcdef0123456789abcdef"
        self.assertEqual(validate_matrix_secret_encryption_key(secret), secret)

    def test_validate_matrix_secret_encryption_key_rejects_invalid_values(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "must be a string"):
            validate_matrix_secret_encryption_key(123)
        with self.assertRaisesRegex(RuntimeError, "must be non-empty"):
            validate_matrix_secret_encryption_key("   ")
        with self.assertRaisesRegex(RuntimeError, "at least 32 characters"):
            validate_matrix_secret_encryption_key("short")
        with self.assertRaisesRegex(RuntimeError, "must not use placeholder"):
            validate_matrix_secret_encryption_key("<set-secret-encryption-key>")

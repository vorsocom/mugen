"""Focused tests for the legacy runtime config import script."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch
import uuid

import sqlalchemy as sa

from scripts import import_legacy_runtime_config as import_mod


def _key_ref_table() -> sa.Table:
    metadata = sa.MetaData()
    return sa.Table(
        "admin_key_ref",
        metadata,
        sa.Column("id", sa.Uuid()),
        sa.Column("tenant_id", sa.Uuid()),
        sa.Column("purpose", sa.String()),
        sa.Column("key_id", sa.String()),
        sa.Column("status", sa.String()),
    )


def _client_profile_table() -> sa.Table:
    metadata = sa.MetaData()
    return sa.Table(
        "admin_messaging_client_profile",
        metadata,
        sa.Column("id", sa.Uuid()),
        sa.Column("tenant_id", sa.Uuid()),
        sa.Column("platform_key", sa.String()),
        sa.Column("profile_key", sa.String()),
    )


def _runtime_config_table() -> sa.Table:
    metadata = sa.MetaData()
    return sa.Table(
        "admin_runtime_config_profile",
        metadata,
        sa.Column("id", sa.Uuid()),
        sa.Column("tenant_id", sa.Uuid()),
        sa.Column("category", sa.String()),
        sa.Column("profile_key", sa.String()),
    )


class _Result:
    def __init__(self, scalar_value=None, first_value=None, all_value=None):
        self._scalar_value = scalar_value
        self._first_value = first_value
        self._all_value = all_value or []

    def scalar_one(self):
        return self._scalar_value

    def first(self):
        return self._first_value

    def all(self):
        return list(self._all_value)


class TestImportLegacyRuntimeConfig(unittest.TestCase):
    """Covers helper normalization and apply orchestration for the import script."""

    def test_parse_args_load_and_helper_primitives(self) -> None:
        with patch(
            "sys.argv",
            [
                "import_legacy_runtime_config.py",
                "--config",
                "custom.toml",
                "--schema",
                "tenant_cfg",
                "--dry-run",
            ],
        ):
            args = import_mod._parse_args()  # pylint: disable=protected-access
        self.assertEqual(args.config, "custom.toml")
        self.assertEqual(args.schema, "tenant_cfg")
        self.assertTrue(args.dry_run)

        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mugen.toml"
            config_path.write_text("[rdbms.sqlalchemy]\nurl = 'postgresql://example'\n")
            self.assertEqual(
                import_mod._load_config(config_path),  # pylint: disable=protected-access
                {"rdbms": {"sqlalchemy": {"url": "postgresql://example"}}},
            )

        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mugen.toml"
            config_path.write_text("", encoding="utf-8")
            with patch.object(import_mod.tomllib, "load", return_value=[]):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "must parse to a TOML table",
                ):
                    import_mod._load_config(config_path)  # pylint: disable=protected-access

        self.assertIsNone(
            import_mod._normalize_optional_text(123)  # pylint: disable=protected-access
        )
        with self.assertRaisesRegex(RuntimeError, "profiles\\[\\]\\.key must be non-empty"):
            import_mod._require_text(None, field_name="profiles[].key")  # pylint: disable=protected-access

        self.assertEqual(import_mod._mapping(["x"]), {})  # pylint: disable=protected-access
        self.assertIsNone(
            import_mod._nested(  # pylint: disable=protected-access
                {"client": "not-a-dict"},
                "client",
                "password",
            )
        )

        payload: dict[str, object] = {}
        import_mod._set_nested(  # pylint: disable=protected-access
            payload,
            ("client", "device"),
            "mugen",
        )
        self.assertEqual(payload, {"client": {"device": "mugen"}})

        with patch.object(import_mod, "MetaData", return_value="meta") as metadata_ctor:
            with patch.object(import_mod, "Table", return_value="table") as table_ctor:
                reflected = import_mod._reflect_table(  # pylint: disable=protected-access
                    "engine",
                    schema="mugen",
                    table_name="admin_key_ref",
                )
        self.assertEqual(reflected, "table")
        metadata_ctor.assert_called_once_with(schema="mugen")
        table_ctor.assert_called_once_with("admin_key_ref", "meta", autoload_with="engine")

    def test_resolve_rdbms_url_and_identifier_validation(self) -> None:
        self.assertEqual(
            import_mod._resolve_rdbms_url(  # pylint: disable=protected-access
                {"rdbms": {"sqlalchemy": {"url": "postgresql://sqlalchemy"}}}
            ),
            "postgresql://sqlalchemy",
        )
        self.assertEqual(
            import_mod._resolve_rdbms_url(  # pylint: disable=protected-access
                {"rdbms": {"alembic": {"url": "postgresql://alembic"}}}
            ),
            "postgresql://alembic",
        )
        with self.assertRaisesRegex(RuntimeError, "Could not resolve relational URL"):
            import_mod._resolve_rdbms_url({})  # pylint: disable=protected-access

        self.assertEqual(
            import_mod._validate_identifier("mugen", "schema name"),  # pylint: disable=protected-access
            "mugen",
        )
        with self.assertRaisesRegex(ValueError, "Invalid schema name"):
            import_mod._validate_identifier("mugen.prod", "schema name")  # pylint: disable=protected-access

    def test_iter_local_key_material_and_key_ref_identity(self) -> None:
        entries, fallback_ids = import_mod._iter_local_key_material(  # pylint: disable=protected-access
            {
                "acp": {
                    "key_management": {
                        "providers": {
                            "local": {
                                "keys": {
                                    "ops_connector_secret": {
                                        "ops_connector_default": "secret-value"
                                    },
                                    "shared_fallback": {"value": "fallback-secret"},
                                }
                            }
                        }
                    }
                }
            }
        )
        self.assertEqual(
            entries,
            [
                import_mod.LocalKeyMaterial(
                    purpose="ops_connector_secret",
                    key_id="ops_connector_default",
                    secret_value="secret-value",
                )
            ],
        )
        self.assertEqual(fallback_ids, ["shared_fallback"])

        extra_entries, extra_fallback_ids = import_mod._iter_local_key_material(  # pylint: disable=protected-access
            {
                "acp": {
                    "key_management": {
                        "providers": {
                            "local": {
                                "keys": {
                                    None: "ignored-secret",
                                    "blank_entry": {"nested": None},
                                    "blank_plain": "   ",
                                    "plain_fallback": "plain-secret",
                                }
                            }
                        }
                    }
                }
            }
        )
        self.assertEqual(extra_entries, [])
        self.assertEqual(extra_fallback_ids, ["plain_fallback"])

        purpose, key_id = import_mod._legacy_managed_key_ref_identity(  # pylint: disable=protected-access
            platform_key="matrix",
            profile_key="default",
            dotted_path="client.password",
        )
        self.assertEqual(purpose, "messaging_client_secret")
        self.assertEqual(key_id, "global.matrix.default.client_password")

        long_purpose, long_key_id = import_mod._legacy_managed_key_ref_identity(  # pylint: disable=protected-access
            platform_key="whatsapp",
            profile_key="profile" * 20,
            dotted_path="graphapi.access_token",
        )
        self.assertEqual(long_purpose, "messaging_client_secret")
        self.assertLessEqual(len(long_key_id), 128)

    def test_extract_legacy_messaging_profiles_and_ops_defaults(self) -> None:
        config = {
            "line": {
                "profiles": [
                    {
                        "key": "support",
                        "channel": {
                            "access_token": "line-access",
                            "secret": "line-secret",
                        },
                        "webhook": {"path_token": "line-path"},
                    }
                ]
            },
            "matrix": {
                "profiles": [
                    {
                        "key": "default",
                        "homeserver": "https://matrix.example.com",
                        "client": {
                            "device": "mugen",
                            "password": "matrix-password",
                            "user": "@bot:example.com",
                        },
                        "profile_displayname": "Bot Display",
                        "room_id": "!room:example.com",
                    }
                ]
            },
            "signal": {
                "profiles": [
                    {
                        "key": "ops",
                        "account": {"number": "+15550000001"},
                        "api": {
                            "base_url": "https://signal.example.com",
                            "bearer_token": "signal-token",
                        },
                    }
                ]
            },
            "telegram": {
                "profiles": [
                    {
                        "key": "bot",
                        "bot": {"token": "telegram-token"},
                        "webhook": {
                            "path_token": "telegram-path",
                            "secret_token": "telegram-secret",
                        },
                    }
                ]
            },
            "wechat": {
                "profiles": [
                    {
                        "key": "wechat",
                        "provider": "official_account",
                        "webhook": {
                            "path_token": "wechat-path",
                            "aes_enabled": True,
                            "aes_key": "wechat-aes",
                            "signature_token": "wechat-signature",
                        },
                        "official_account": {
                            "app_id": "wx-app-id",
                            "app_secret": "wx-app-secret",
                        },
                        "wecom": {
                            "corp_id": "corp-id",
                            "agent_id": "agent-id",
                            "corp_secret": "corp-secret",
                        },
                    }
                ]
            },
            "whatsapp": {
                "profiles": [
                    {
                        "key": "whatsapp",
                        "app": {"id": "app-id", "secret": "app-secret"},
                        "business": {"phone_number_id": "phone-1"},
                        "graphapi": {"access_token": "graph-token"},
                        "webhook": {
                            "path_token": "whatsapp-path",
                            "verification_token": "verify-token",
                        },
                    }
                ]
            },
            "ops_connector": {
                "timeout_seconds_default": 12.5,
                "max_retries_default": 4,
                "retry_backoff_seconds_default": 1.0,
                "retry_status_codes_default": [429, 503],
                "redacted_keys": ["password", "token"],
                "secret_purpose": "ops_connector_secret",
            },
        }

        profiles = import_mod._extract_legacy_messaging_profiles(  # pylint: disable=protected-access
            config
        )
        self.assertEqual(len(profiles), 6)
        matrix_profile = next(
            profile for profile in profiles if profile.platform_key == "matrix"
        )
        self.assertEqual(matrix_profile.display_name, "Bot Display")
        self.assertEqual(
            matrix_profile.settings["client"]["device"],
            "mugen",
        )
        self.assertEqual(
            matrix_profile.secret_values["client.password"],
            "matrix-password",
        )
        self.assertEqual(matrix_profile.recipient_user_id, "@bot:example.com")

        whatsapp_profile = next(
            profile for profile in profiles if profile.platform_key == "whatsapp"
        )
        self.assertEqual(whatsapp_profile.phone_number_id, "phone-1")
        self.assertEqual(whatsapp_profile.settings, {"app": {"id": "app-id"}})
        self.assertIn("graphapi.access_token", whatsapp_profile.secret_values)

        self.assertEqual(
            import_mod._ops_connector_defaults(config),  # pylint: disable=protected-access
            {
                "timeout_seconds_default": 12.5,
                "max_retries_default": 4,
                "retry_backoff_seconds_default": 1.0,
                "retry_status_codes_default": [429, 503],
                "redacted_keys": ["password", "token"],
            },
        )

        assistant_profile = import_mod._extract_legacy_profile(  # pylint: disable=protected-access
            platform_key="matrix",
            payload={
                "key": "assistant",
                "assistant": {"name": "Matrix Assistant"},
                "client": {"user": "@assistant:example.com"},
            },
        )
        self.assertEqual(assistant_profile.display_name, "Matrix Assistant")
        self.assertEqual(assistant_profile.secret_values, {})

        whatsapp_profile = import_mod._extract_legacy_profile(  # pylint: disable=protected-access
            platform_key="whatsapp",
            payload={
                "key": "whatsapp-direct",
                "business": {"phone_number_id": "phone-9"},
            },
        )
        self.assertEqual(whatsapp_profile.platform_key, "whatsapp")
        self.assertEqual(whatsapp_profile.phone_number_id, "phone-9")
        self.assertEqual(whatsapp_profile.settings, {})

    def test_extract_legacy_profiles_skip_non_dict_and_missing_secret_values(self) -> None:
        profiles = import_mod._extract_legacy_messaging_profiles(  # pylint: disable=protected-access
            {
                "line": {"profiles": ["ignore-me", {"key": "line-empty", "channel": {}}]},
                "signal": {"profiles": [{"key": "signal-empty", "account": {}}]},
                "telegram": {"profiles": [{"key": "telegram-empty", "webhook": {}}]},
                "wechat": {
                    "profiles": [
                        {
                            "key": "wechat-empty",
                            "provider": "wecom",
                            "webhook": {},
                            "official_account": {},
                            "wecom": {},
                        }
                    ]
                },
                "whatsapp": {
                    "profiles": [
                        {
                            "key": "whatsapp-empty",
                            "app": {},
                            "business": {},
                            "graphapi": {},
                            "webhook": {},
                        }
                    ]
                },
            }
        )

        self.assertEqual(
            [profile.profile_key for profile in profiles],
            [
                "line-empty",
                "signal-empty",
                "telegram-empty",
                "wechat-empty",
                "whatsapp-empty",
            ],
        )
        self.assertTrue(all(profile.secret_values == {} for profile in profiles))

    def test_upsert_helpers_build_statements_and_reject_destroyed_rows(self) -> None:
        conn = Mock()
        key_ref_table = _key_ref_table()
        client_profile_table = _client_profile_table()
        runtime_config_table = _runtime_config_table()

        with self.assertRaisesRegex(RuntimeError, "destroyed KeyRef"):
            conn.execute.side_effect = [
                _Result(first_value=SimpleNamespace(id=uuid.uuid4(), status="destroyed"))
            ]
            import_mod._upsert_managed_key_ref(  # pylint: disable=protected-access
                conn,
                key_ref_table=key_ref_table,
                tenant_id=uuid.uuid4(),
                purpose="audit_hmac",
                key_id="key-1",
                encrypted_secret="enc",
                attributes=None,
            )

        key_ref_id = uuid.uuid4()
        conn.execute.side_effect = [_Result(first_value=None), _Result(scalar_value=key_ref_id)]
        self.assertEqual(
            import_mod._upsert_managed_key_ref(  # pylint: disable=protected-access
                conn,
                key_ref_table=key_ref_table,
                tenant_id=uuid.uuid4(),
                purpose="audit_hmac",
                key_id="key-1",
                encrypted_secret="enc",
                attributes={"source": "test"},
            ),
            key_ref_id,
        )

        client_profile_id = uuid.uuid4()
        conn.execute.side_effect = [_Result(scalar_value=client_profile_id)]
        self.assertEqual(
            import_mod._upsert_messaging_client_profile(  # pylint: disable=protected-access
                conn,
                client_profile_table=client_profile_table,
                profile=import_mod.LegacyMessagingProfile(
                    platform_key="matrix",
                    profile_key="default",
                    display_name="Bot",
                    settings={"client": {"device": "mugen"}},
                    secret_values={"client.password": "secret"},
                    recipient_user_id="@bot:example.com",
                ),
                secret_refs={"client.password": str(uuid.uuid4())},
            ),
            client_profile_id,
        )

        runtime_profile_id = uuid.uuid4()
        conn.execute.side_effect = [_Result(scalar_value=runtime_profile_id)]
        self.assertEqual(
            import_mod._upsert_runtime_config_profile(  # pylint: disable=protected-access
                conn,
                runtime_config_table=runtime_config_table,
                settings_json={"timeout_seconds_default": 12.5},
            ),
            runtime_profile_id,
        )

    def test_import_runtime_config_dry_run_and_apply(self) -> None:
        config = {
            "acp": {
                "key_management": {
                    "providers": {
                        "managed": {
                            "encryption_key": "0123456789012345678901234567890123456789"
                        },
                        "local": {
                            "keys": {
                                "ops_connector_secret": {
                                    "ops_connector_default": "local-secret"
                                }
                            }
                        },
                    }
                }
            },
            "rdbms": {"sqlalchemy": {"url": "postgresql://example"}},
            "ops_connector": {"timeout_seconds_default": 12.5},
        }

        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(
                import_mod.import_runtime_config(
                    config_path=Path("mugen.toml"),
                    schema="mugen",
                    dry_run=True,
                ),
                0,
            )
        self.assertIn("DRY_RUN: no DB changes applied", stdout.getvalue())

        fake_engine = Mock()
        fake_conn = Mock()
        fake_context = MagicMock()
        fake_context.__enter__.return_value = fake_conn
        fake_context.__exit__.return_value = False
        fake_engine.begin.return_value = fake_context

        with (
            patch.object(import_mod, "_load_config", return_value=config),
            patch.object(import_mod.sa, "create_engine", return_value=fake_engine),
            patch.object(
                import_mod,
                "_reflect_table",
                side_effect=[
                    _key_ref_table(),
                    _client_profile_table(),
                    _runtime_config_table(),
                ],
            ),
            patch.object(
                import_mod,
                "_upsert_managed_key_ref",
                side_effect=[uuid.uuid4()],
            ) as upsert_key_ref,
            patch.object(
                import_mod,
                "_upsert_messaging_client_profile",
                return_value=uuid.uuid4(),
            ) as upsert_profile,
            patch.object(
                import_mod,
                "_upsert_runtime_config_profile",
                return_value=uuid.uuid4(),
            ) as upsert_runtime_profile,
        ):
            stdout = StringIO()
            with redirect_stdout(stdout):
                result = import_mod.import_runtime_config(
                    config_path=Path("mugen.toml"),
                    schema="mugen",
                    dry_run=False,
                )

        self.assertEqual(result, 0)
        self.assertTrue(upsert_key_ref.called)
        self.assertFalse(upsert_profile.called)
        upsert_runtime_profile.assert_called_once()
        self.assertIn("IMPORT_APPLIED", stdout.getvalue())
        self.assertIn("cleanup_next_steps:", stdout.getvalue())

    def test_import_runtime_config_applies_fallbacks_and_legacy_profiles(self) -> None:
        config = {
            "acp": {
                "key_management": {
                    "providers": {
                        "managed": {
                            "encryption_key": "0123456789012345678901234567890123456789"
                        },
                        "local": {
                            "keys": {
                                "ops_connector_secret": {
                                    "ops_connector_default": "local-secret"
                                },
                                "matrix_password": {"value": "fallback-secret"},
                            }
                        },
                    }
                }
            },
            "rdbms": {"sqlalchemy": {"url": "postgresql://example"}},
            "matrix": {
                "profiles": [
                    {
                        "key": "default",
                        "homeserver": "https://matrix.example.com",
                        "client": {
                            "device": "mugen",
                            "password": "matrix-password",
                            "user": "@bot:example.com",
                        },
                    }
                ]
            },
            "ops_connector": {"timeout_seconds_default": 12.5},
        }

        fake_engine = Mock()
        fake_conn = Mock()
        fake_context = MagicMock()
        fake_context.__enter__.return_value = fake_conn
        fake_context.__exit__.return_value = False
        fake_engine.begin.return_value = fake_context
        fake_conn.execute.side_effect = [
            _Result(all_value=[SimpleNamespace(purpose="messaging_client_secret")]),
        ]

        key_ref_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        with (
            patch.object(import_mod, "_load_config", return_value=config),
            patch.object(import_mod.sa, "create_engine", return_value=fake_engine),
            patch.object(
                import_mod,
                "_reflect_table",
                side_effect=[
                    _key_ref_table(),
                    _client_profile_table(),
                    _runtime_config_table(),
                ],
            ),
            patch.object(
                import_mod,
                "_upsert_managed_key_ref",
                side_effect=key_ref_ids,
            ) as upsert_key_ref,
            patch.object(
                import_mod,
                "_upsert_messaging_client_profile",
                return_value=uuid.uuid4(),
            ) as upsert_profile,
            patch.object(
                import_mod,
                "_upsert_runtime_config_profile",
                return_value=uuid.uuid4(),
            ) as upsert_runtime_profile,
        ):
            stdout = StringIO()
            with redirect_stdout(stdout):
                result = import_mod.import_runtime_config(
                    config_path=Path("mugen.toml"),
                    schema="mugen",
                    dry_run=False,
                )

        self.assertEqual(result, 0)
        self.assertEqual(upsert_key_ref.call_count, 3)
        upsert_profile.assert_called_once()
        upsert_runtime_profile.assert_called_once()
        profile_call = upsert_profile.call_args.kwargs
        self.assertEqual(
            profile_call["secret_refs"],
            {"client.password": str(key_ref_ids[-1])},
        )
        output = stdout.getvalue()
        self.assertIn("fallback_key_ref_updates=1", output)
        self.assertIn("imported_messaging_profiles=1", output)

    def test_import_runtime_config_skips_unresolved_fallback_secret(self) -> None:
        config = {
            "acp": {
                "key_management": {
                    "providers": {
                        "managed": {
                            "encryption_key": "0123456789012345678901234567890123456789"
                        },
                        "local": {"keys": {"matrix_password": {"env": "MISSING_ENV"}}},
                    }
                }
            },
            "rdbms": {"sqlalchemy": {"url": "postgresql://example"}},
        }

        fake_engine = Mock()
        fake_conn = Mock()
        fake_context = MagicMock()
        fake_context.__enter__.return_value = fake_conn
        fake_context.__exit__.return_value = False
        fake_engine.begin.return_value = fake_context
        fake_conn.execute.side_effect = [
            _Result(all_value=[SimpleNamespace(purpose="messaging_client_secret")]),
        ]

        with patch.dict("os.environ", {}, clear=True):
            with (
                patch.object(import_mod, "_load_config", return_value=config),
                patch.object(import_mod.sa, "create_engine", return_value=fake_engine),
                patch.object(
                    import_mod,
                    "_reflect_table",
                    side_effect=[
                        _key_ref_table(),
                        _client_profile_table(),
                        _runtime_config_table(),
                    ],
                ),
                patch.object(
                    import_mod,
                    "_upsert_managed_key_ref",
                    return_value=uuid.uuid4(),
                ) as upsert_key_ref,
                patch.object(
                    import_mod,
                    "_upsert_messaging_client_profile",
                    return_value=uuid.uuid4(),
                ) as upsert_profile,
                patch.object(
                    import_mod,
                    "_upsert_runtime_config_profile",
                    return_value=uuid.uuid4(),
                ) as upsert_runtime_profile,
            ):
                result = import_mod.import_runtime_config(
                    config_path=Path("mugen.toml"),
                    schema="mugen",
                    dry_run=False,
                )

        self.assertEqual(result, 0)
        upsert_key_ref.assert_not_called()
        upsert_profile.assert_not_called()
        upsert_runtime_profile.assert_called_once()

    def test_main_uses_parsed_args_and_resolved_config_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mugen.toml"
            config_path.write_text("", encoding="utf-8")

            with (
                patch.object(
                    import_mod,
                    "_parse_args",
                    return_value=SimpleNamespace(
                        config=str(config_path),
                        schema="mugen",
                        dry_run=True,
                    ),
                ),
                patch.object(
                    import_mod,
                    "import_runtime_config",
                    return_value=0,
                ) as import_runtime,
            ):
                self.assertEqual(import_mod.main(), 0)

        import_runtime.assert_called_once_with(
            config_path=config_path,
            schema="mugen",
            dry_run=True,
        )

    def test_main_missing_config_and_runpy_entrypoint(self) -> None:
        with patch.object(
            import_mod,
            "_parse_args",
            return_value=SimpleNamespace(
                config="missing.toml",
                schema="mugen",
                dry_run=True,
            ),
        ):
            with self.assertRaisesRegex(FileNotFoundError, "Config file not found"):
                import_mod.main()

        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mugen.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "[acp.key_management.providers.managed]",
                        "encryption_key = \"0123456789012345678901234567890123456789\"",
                        "",
                        "[rdbms.sqlalchemy]",
                        "url = \"postgresql://example\"",
                    ]
                ),
                encoding="utf-8",
            )
            with (
                patch(
                    "sys.argv",
                    [
                        "import_legacy_runtime_config.py",
                        "--config",
                        str(config_path),
                        "--dry-run",
                    ],
                ),
                self.assertRaises(SystemExit) as ctx,
            ):
                runpy.run_path(
                    str(Path(import_mod.__file__).resolve()),
                    run_name="__main__",
                )
        self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()

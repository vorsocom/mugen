"""Unit tests for ACP phase4 key/capability security services."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
import os
import sys
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException


def _bootstrap_namespace_packages() -> None:
    root = Path(__file__).resolve().parents[1] / "mugen"

    if "mugen" not in sys.modules:
        mugen_pkg = ModuleType("mugen")
        mugen_pkg.__path__ = [str(root)]
        sys.modules["mugen"] = mugen_pkg

    if "mugen.core" not in sys.modules:
        core_pkg = ModuleType("mugen.core")
        core_pkg.__path__ = [str(root / "core")]
        sys.modules["mugen.core"] = core_pkg
        setattr(sys.modules["mugen"], "core", core_pkg)

    if "mugen.core.di" not in sys.modules:
        di_mod = ModuleType("mugen.core.di")
        di_mod.container = SimpleNamespace(config=SimpleNamespace())
        sys.modules["mugen.core.di"] = di_mod
        setattr(sys.modules["mugen.core"], "di", di_mod)


_bootstrap_namespace_packages()

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.constants import GLOBAL_TENANT_ID
from mugen.core.plugin.acp.contract.service.key_provider import ResolvedKeyMaterial
from mugen.core.plugin.acp.domain import KeyRefDE, PluginCapabilityGrantDE
from mugen.core.plugin.acp.service.key_provider import (
    KeyMaterialResolver,
    LocalConfigKeyMaterialProvider,
    ManagedEncryptedKeyMaterialProvider,
    ManagedKeyMaterialCipher,
)
from mugen.core.plugin.acp.service.key_ref import KeyRefService
from mugen.core.plugin.acp.service.plugin_capability_grant import (
    PluginCapabilityGrantService,
)


class _Provider:
    def __init__(self, name: str, value: bytes | None):
        self._name = name
        self._value = value

    @property
    def name(self) -> str:
        return self._name

    def resolve(self, _key_ref: KeyRefDE) -> bytes | None:
        return self._value


class TestLocalConfigKeyMaterialProvider(unittest.TestCase):
    """Covers local key-provider and resolver branches."""

    def test_to_mapping_and_resolve_secret_helpers(self) -> None:
        with patch(
            "mugen.core.plugin.acp.service.key_provider.di.container",
            new=SimpleNamespace(config="cfg"),
        ):
            from mugen.core.plugin.acp.service import key_provider as key_provider_mod

            self.assertEqual(key_provider_mod._config_provider(), "cfg")

        self.assertEqual(LocalConfigKeyMaterialProvider._to_mapping({"a": 1}), {"a": 1})
        self.assertEqual(
            LocalConfigKeyMaterialProvider._to_mapping(SimpleNamespace(a=2)),
            {"a": 2},
        )
        self.assertEqual(LocalConfigKeyMaterialProvider._to_mapping("x"), {})

        self.assertIsNone(LocalConfigKeyMaterialProvider._resolve_secret(None))
        self.assertIsNone(LocalConfigKeyMaterialProvider._resolve_secret("   "))
        self.assertEqual(
            LocalConfigKeyMaterialProvider._resolve_secret({"value": " secret "}),
            "secret",
        )

        with patch.dict(os.environ, {"PHASE4_ENV_SECRET": "env-secret"}, clear=False):
            self.assertEqual(
                LocalConfigKeyMaterialProvider._resolve_secret(
                    {"env": "PHASE4_ENV_SECRET"}
                ),
                "env-secret",
            )
            self.assertEqual(
                LocalConfigKeyMaterialProvider._resolve_secret("env:PHASE4_ENV_SECRET"),
                "env-secret",
            )

    def test_resolve_uses_local_map_then_audit_fallback(self) -> None:
        config = SimpleNamespace(
            acp=SimpleNamespace(
                key_management=SimpleNamespace(
                    providers={
                        "local": {
                            "keys": {
                                "audit_hmac": {
                                    "key-1": "primary-secret",
                                    "key-2": {"env": "PHASE4_ENV_SECRET"},
                                },
                                "key-fallback": "global-fallback-secret",
                            }
                        }
                    }
                )
            ),
            audit=SimpleNamespace(
                hash_chain=SimpleNamespace(keys={"audit-old": "legacy-secret"})
            ),
        )
        provider = LocalConfigKeyMaterialProvider(config_provider=lambda: config)

        row = KeyRefDE(purpose="audit_hmac", key_id="key-1", provider="local")
        self.assertEqual(provider.resolve(row), b"primary-secret")

        with patch.dict(os.environ, {"PHASE4_ENV_SECRET": "env-secret"}, clear=False):
            row = KeyRefDE(purpose="audit_hmac", key_id="key-2", provider="local")
            self.assertEqual(provider.resolve(row), b"env-secret")

        row = KeyRefDE(purpose="other", key_id="key-fallback", provider="local")
        self.assertEqual(provider.resolve(row), b"global-fallback-secret")

        row = KeyRefDE(purpose="audit_hmac", key_id="audit-old", provider="local")
        self.assertEqual(provider.resolve(row), b"legacy-secret")

        self.assertIsNone(
            provider._lookup_local_secret(
                key_ref=KeyRefDE(purpose="audit_hmac", key_id=" ")
            )
        )
        self.assertIsNone(
            provider.resolve(
                KeyRefDE(
                    purpose="audit_hmac",
                    key_id="missing",
                    provider="local",
                )
            )
        )
        self.assertIsNone(
            provider.resolve(
                KeyRefDE(purpose="audit_hmac", key_id=" ", provider="local")
            )
        )
        self.assertIsNone(
            provider.resolve(
                KeyRefDE(purpose="audit_hmac", key_id="key-1", provider="kms")
            )
        )

    def test_key_material_resolver_paths(self) -> None:
        row = KeyRefDE(key_id="key-1", provider="local")

        resolver = KeyMaterialResolver(providers=[_Provider("local", b"secret")])
        resolved = resolver.resolve(row)
        self.assertIsInstance(resolved, ResolvedKeyMaterial)
        assert resolved is not None
        self.assertEqual(resolved.provider, "local")
        self.assertEqual(resolved.secret, b"secret")

        self.assertIsNone(resolver.resolve(KeyRefDE(key_id="key-1", provider=" ")))
        self.assertIsNone(
            resolver.resolve(KeyRefDE(key_id="key-1", provider="missing"))
        )
        self.assertIsNone(
            KeyMaterialResolver(providers=[_Provider("local", None)]).resolve(row)
        )
        self.assertIsNone(
            KeyMaterialResolver(providers=[_Provider("local", b"secret")]).resolve(
                KeyRefDE(key_id=" ", provider="local")
            )
        )

    def test_managed_key_material_cipher_and_provider_paths(self) -> None:
        config = SimpleNamespace(
            acp=SimpleNamespace(
                key_management=SimpleNamespace(
                    providers={
                        "managed": {
                            "encryption_key": (
                                "0123456789012345678901234567890123456789"
                            )
                        }
                    }
                )
            )
        )
        cipher = ManagedKeyMaterialCipher(config_provider=lambda: config)
        encrypted = cipher.encrypt("super-secret")
        self.assertNotEqual(encrypted, "super-secret")
        self.assertEqual(cipher.decrypt(encrypted), b"super-secret")

        provider = ManagedEncryptedKeyMaterialProvider(
            config_provider=lambda: config,
            cipher=cipher,
        )
        self.assertEqual(
            provider.resolve(
                KeyRefDE(
                    key_id="key-1",
                    provider="managed",
                    encrypted_secret=encrypted,
                )
            ),
            b"super-secret",
        )
        self.assertIsNone(
            provider.resolve(
                KeyRefDE(key_id="key-1", provider="managed", encrypted_secret=None)
            )
        )
        self.assertIsNone(
            provider.resolve(
                KeyRefDE(key_id="key-1", provider="local", encrypted_secret=encrypted)
            )
        )

        missing_cfg = SimpleNamespace(
            acp=SimpleNamespace(
                key_management=SimpleNamespace(providers={"managed": {}})
            )
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "acp.key_management.providers.managed.encryption_key",
        ):
            ManagedKeyMaterialCipher(config_provider=lambda: missing_cfg).encrypt(
                "value"
            )

        wrong_cfg = SimpleNamespace(
            acp=SimpleNamespace(
                key_management=SimpleNamespace(
                    providers={
                        "managed": {
                            "encryption_key": (
                                "9999999999999999999999999999999999999999"
                            )
                        }
                    }
                )
            )
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "could not be decrypted",
        ):
            ManagedEncryptedKeyMaterialProvider(
                config_provider=lambda: wrong_cfg,
            ).resolve(
                KeyRefDE(
                    key_id="key-1",
                    provider="managed",
                    encrypted_secret=encrypted,
                )
            )

        self.assertEqual(ManagedKeyMaterialCipher._to_mapping("x"), {})
        with self.assertRaisesRegex(RuntimeError, "SecretValue must be a string"):
            cipher.encrypt(123)  # type: ignore[arg-type]


class TestKeyRefService(unittest.IsolatedAsyncioTestCase):
    """Covers key reference action workflows and resolution precedence."""

    async def test_create_normalizes_and_defaults(self) -> None:
        self.assertIsNotNone(KeyRefService._now_utc().tzinfo)
        self.assertEqual(KeyRefService._normalize_provider(" "), "local")
        with self.assertRaises(HTTPException) as ctx:
            KeyRefService._normalize_required_text(" ", field_name="Purpose")
        self.assertEqual(ctx.exception.code, 400)
        self.assertIsNone(KeyRefService._normalize_secret_value(None))
        with self.assertRaises(HTTPException) as ctx:
            KeyRefService._normalize_secret_value(1)
        self.assertEqual(ctx.exception.code, 400)
        with self.assertRaises(HTTPException) as ctx:
            KeyRefService._normalize_secret_value("   ")
        self.assertEqual(ctx.exception.code, 400)
        self.assertEqual(
            KeyRefService._normalize_secret_value("secret-value"),
            "secret-value",
        )

        svc = KeyRefService(
            table="admin_key_ref",
            rsg=Mock(),
            key_material_resolver=Mock(),
        )
        created = KeyRefDE(
            id=uuid.uuid4(),
            tenant_id=GLOBAL_TENANT_ID,
            purpose="audit_hmac",
            key_id="key-1",
            provider="local",
            status="active",
        )

        with patch.object(
            IRelationalService,
            "create",
            new=AsyncMock(return_value=created),
        ) as base_create:
            result = await svc.create(
                {
                    "tenant_id": None,
                    "purpose": " audit_hmac ",
                    "key_id": " key-1 ",
                    "provider": " LOCAL ",
                    "status": None,
                }
            )

        self.assertEqual(result.id, created.id)
        payload = base_create.await_args.args[0]
        self.assertEqual(payload["tenant_id"], GLOBAL_TENANT_ID)
        self.assertEqual(payload["purpose"], "audit_hmac")
        self.assertEqual(payload["key_id"], "key-1")
        self.assertEqual(payload["provider"], "local")
        self.assertEqual(payload["status"], "active")

        with patch.object(
            IRelationalService,
            "create",
            new=AsyncMock(return_value=created),
        ) as base_create:
            explicit_tenant_id = uuid.uuid4()
            with self.assertRaises(HTTPException) as ctx:
                await svc.create(
                    {
                        "tenant_id": explicit_tenant_id,
                        "purpose": "audit_hmac",
                        "key_id": "key-1",
                        "provider": "local",
                        "status": "retired",
                    }
                )
        self.assertEqual(ctx.exception.code, 409)
        base_create.assert_not_awaited()

        with self.assertRaises(HTTPException) as ctx:
            await svc.create(
                {
                    "tenant_id": None,
                    "purpose": "audit_hmac",
                    "key_id": "managed-key",
                    "provider": "managed",
                }
            )
        self.assertEqual(ctx.exception.code, 400)

        managed_created = KeyRefDE(
            id=uuid.uuid4(),
            tenant_id=GLOBAL_TENANT_ID,
            purpose="audit_hmac",
            key_id="managed-key",
            provider="managed",
            status="active",
            has_material=True,
        )
        with patch.object(
            IRelationalService,
            "create",
            new=AsyncMock(return_value=managed_created),
        ) as base_create:
            result = await svc.create(
                {
                    "_allow_managed_create": True,
                    "tenant_id": None,
                    "purpose": "audit_hmac",
                    "key_id": "managed-key",
                    "provider": "managed",
                    "encrypted_secret": "ciphertext",
                }
            )
        self.assertEqual(result.id, managed_created.id)
        self.assertTrue(base_create.await_args.args[0]["has_material"])

        with patch.object(
            IRelationalService,
            "create",
            new=AsyncMock(return_value=created),
        ) as base_create:
            await svc.create(
                {
                    "tenant_id": None,
                    "purpose": "audit_hmac",
                    "key_id": "key-4",
                    "provider": "local",
                    "encrypted_secret": "should-clear",
                    "has_material": False,
                }
            )
        self.assertIsNone(base_create.await_args.args[0]["encrypted_secret"])

        with patch.object(
            IRelationalService,
            "create",
            new=AsyncMock(return_value=created),
        ) as base_create:
            await svc.create(
                {
                    "tenant_id": None,
                    "purpose": "audit_hmac",
                    "key_id": "key-5",
                    "provider": "local",
                    "status": "retired",
                }
            )
        self.assertEqual(base_create.await_args.args[0]["status"], "retired")

    async def test_get_for_action_branches(self) -> None:
        svc = KeyRefService(
            table="admin_key_ref", rsg=Mock(), key_material_resolver=Mock()
        )
        where = {"id": uuid.uuid4()}
        row = KeyRefDE(id=where["id"], row_version=2)

        svc.get = AsyncMock(return_value=row)
        found = await svc._get_for_action(
            where=where, expected_row_version=2, not_found="x"
        )
        self.assertEqual(found.id, where["id"])

        svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(
                where=where, expected_row_version=2, not_found="x"
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.get = AsyncMock(side_effect=[None, None])
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(
                where=where, expected_row_version=2, not_found="missing"
            )
        self.assertEqual(ctx.exception.code, 404)

        svc.get = AsyncMock(side_effect=[None, KeyRefDE(id=where["id"], row_version=3)])
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(
                where=where, expected_row_version=2, not_found="missing"
            )
        self.assertEqual(ctx.exception.code, 409)

        svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(
                where=where, expected_row_version=2, not_found="missing"
            )
        self.assertEqual(ctx.exception.code, 500)

    async def test_activate_rotate_retire_destroy_paths(self) -> None:
        tenant_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        now = datetime(2026, 2, 25, 20, 0, tzinfo=timezone.utc)

        svc = KeyRefService(
            table="admin_key_ref",
            rsg=Mock(),
            key_material_resolver=Mock(),
            managed_key_material_cipher=Mock(
                encrypt=Mock(return_value="encrypted-managed")
            ),
        )
        svc._now_utc = lambda: now

        existing = KeyRefDE(
            id=uuid.uuid4(),
            tenant_id=GLOBAL_TENANT_ID,
            purpose="audit_hmac",
            key_id="key-1",
            provider="local",
            status="active",
            row_version=1,
        )

        svc.get = AsyncMock(return_value=existing)
        svc.update = AsyncMock()
        svc.create = AsyncMock()
        same = await svc._activate(
            tenant_id=GLOBAL_TENANT_ID,
            purpose="audit_hmac",
            key_id="key-1",
            provider="local",
            auth_user_id=auth_user_id,
            attributes=None,
        )
        self.assertEqual(same.id, existing.id)
        svc.update.assert_not_awaited()

        candidate = KeyRefDE(
            id=uuid.uuid4(),
            tenant_id=GLOBAL_TENANT_ID,
            purpose="audit_hmac",
            key_id="key-2",
            provider="local",
            status="retired",
            row_version=1,
        )
        updated_candidate = KeyRefDE(
            id=candidate.id,
            tenant_id=GLOBAL_TENANT_ID,
            purpose="audit_hmac",
            key_id="key-2",
            provider="local",
            status="active",
            row_version=2,
        )

        svc.get = AsyncMock(side_effect=[existing, candidate])
        svc.update = AsyncMock(side_effect=[existing, updated_candidate])
        activated = await svc._activate(
            tenant_id=GLOBAL_TENANT_ID,
            purpose="audit_hmac",
            key_id="key-2",
            provider="local",
            auth_user_id=auth_user_id,
            attributes={"rotated": True},
        )
        self.assertEqual(activated.status, "active")

        svc.get = AsyncMock(side_effect=[None, None])
        created = KeyRefDE(
            id=uuid.uuid4(),
            tenant_id=GLOBAL_TENANT_ID,
            purpose="audit_hmac",
            key_id="key-3",
            provider="local",
            status="active",
            row_version=1,
        )
        svc.create = AsyncMock(return_value=created)
        inserted = await svc._activate(
            tenant_id=GLOBAL_TENANT_ID,
            purpose="audit_hmac",
            key_id="key-3",
            provider="local",
            auth_user_id=auth_user_id,
            attributes=None,
        )
        self.assertEqual(inserted.id, created.id)

        svc.get = AsyncMock(
            side_effect=[None, KeyRefDE(id=uuid.uuid4(), status="destroyed")]
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._activate(
                tenant_id=GLOBAL_TENANT_ID,
                purpose="audit_hmac",
                key_id="key-x",
                provider="local",
                auth_user_id=auth_user_id,
                attributes=None,
            )
        self.assertEqual(ctx.exception.code, 409)

        svc.get = AsyncMock(side_effect=[existing, candidate])
        svc.update = AsyncMock(side_effect=[existing, None])
        with self.assertRaises(HTTPException) as ctx:
            await svc._activate(
                tenant_id=GLOBAL_TENANT_ID,
                purpose="audit_hmac",
                key_id="key-2",
                provider="local",
                auth_user_id=auth_user_id,
                attributes=None,
            )
        self.assertEqual(ctx.exception.code, 409)

        svc.get = AsyncMock(side_effect=[existing, candidate])
        svc.update = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._activate(
                tenant_id=GLOBAL_TENANT_ID,
                purpose="audit_hmac",
                key_id="key-2",
                provider="local",
                auth_user_id=auth_user_id,
                attributes=None,
            )
        self.assertEqual(ctx.exception.code, 500)

        managed_current = KeyRefDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            purpose="audit_hmac",
            key_id="managed-key",
            provider="managed",
            status="active",
            row_version=3,
        )
        managed_updated = KeyRefDE(
            id=managed_current.id,
            tenant_id=tenant_id,
            purpose="audit_hmac",
            key_id="managed-key",
            provider="managed",
            status="active",
            row_version=4,
            has_material=True,
        )
        svc.get = AsyncMock(return_value=managed_current)
        svc.update = AsyncMock(return_value=managed_updated)
        rotated_managed = await svc._activate(
            tenant_id=tenant_id,
            purpose="audit_hmac",
            key_id="managed-key",
            provider="managed",
            auth_user_id=auth_user_id,
            attributes={"rotated": True},
            secret_value="s3cret",
        )
        self.assertEqual(rotated_managed.id, managed_current.id)
        self.assertEqual(
            svc.update.await_args.args[1]["encrypted_secret"],
            "encrypted-managed",
        )

        with self.assertRaises(HTTPException) as ctx:
            await svc._activate(
                tenant_id=tenant_id,
                purpose="audit_hmac",
                key_id="managed-key",
                provider="managed",
                auth_user_id=auth_user_id,
                attributes=None,
                secret_value=None,
            )
        self.assertEqual(ctx.exception.code, 400)

        with self.assertRaises(HTTPException) as ctx:
            await svc._activate(
                tenant_id=GLOBAL_TENANT_ID,
                purpose="audit_hmac",
                key_id="key-1",
                provider="local",
                auth_user_id=auth_user_id,
                attributes=None,
                secret_value="unexpected",
            )
        self.assertEqual(ctx.exception.code, 400)

        with self.assertRaises(HTTPException) as ctx:
            await svc._activate(
                tenant_id=tenant_id,
                purpose="audit_hmac",
                key_id="local-key",
                provider="local",
                auth_user_id=auth_user_id,
                attributes=None,
                secret_value=None,
            )
        self.assertEqual(ctx.exception.code, 409)

        svc.get = AsyncMock(return_value=managed_current)
        svc.update = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._activate(
                tenant_id=tenant_id,
                purpose="audit_hmac",
                key_id="managed-key",
                provider="managed",
                auth_user_id=auth_user_id,
                attributes=None,
                secret_value="s3cret",
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.get = AsyncMock(return_value=managed_current)
        svc.update = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc._activate(
                tenant_id=tenant_id,
                purpose="audit_hmac",
                key_id="managed-key",
                provider="managed",
                auth_user_id=auth_user_id,
                attributes=None,
                secret_value="s3cret",
            )
        self.assertEqual(ctx.exception.code, 409)

        active_row = KeyRefDE(id=uuid.uuid4(), status="active", row_version=4)
        retired_row = KeyRefDE(id=active_row.id, status="retired", row_version=5)
        destroyed_row = KeyRefDE(id=active_row.id, status="destroyed", row_version=6)

        svc._get_for_action = AsyncMock(return_value=active_row)
        svc.update_with_row_version = AsyncMock(return_value=retired_row)
        payload, code = await svc._retire(
            where={"id": active_row.id},
            auth_user_id=auth_user_id,
            data=SimpleNamespace(row_version=4, reason=" rotate "),
            not_found="missing",
        )
        self.assertEqual(code, 200)
        self.assertEqual(payload["Status"], "retired")

        svc._get_for_action = AsyncMock(
            return_value=KeyRefDE(id=uuid.uuid4(), status="retired")
        )
        payload, code = await svc._retire(
            where={"id": uuid.uuid4()},
            auth_user_id=auth_user_id,
            data=SimpleNamespace(row_version=1, reason=None),
            not_found="missing",
        )
        self.assertEqual((code, payload["Status"]), (200, "retired"))

        svc._get_for_action = AsyncMock(
            return_value=KeyRefDE(id=uuid.uuid4(), status="destroyed")
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc._retire(
                where={"id": uuid.uuid4()},
                auth_user_id=auth_user_id,
                data=SimpleNamespace(row_version=1, reason=None),
                not_found="missing",
            )
        self.assertEqual(ctx.exception.code, 409)

        svc._get_for_action = AsyncMock(return_value=active_row)
        svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._retire(
                where={"id": active_row.id},
                auth_user_id=auth_user_id,
                data=SimpleNamespace(row_version=4, reason=None),
                not_found="missing",
            )
        self.assertEqual(ctx.exception.code, 500)

        svc._get_for_action = AsyncMock(return_value=active_row)
        svc.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc._retire(
                where={"id": active_row.id},
                auth_user_id=auth_user_id,
                data=SimpleNamespace(row_version=4, reason=None),
                not_found="missing",
            )
        self.assertEqual(ctx.exception.code, 409)

        svc._get_for_action = AsyncMock(return_value=active_row)
        svc.update_with_row_version = AsyncMock(return_value=destroyed_row)
        payload, code = await svc._destroy(
            where={"id": active_row.id},
            auth_user_id=auth_user_id,
            data=SimpleNamespace(row_version=4, reason="purged"),
            not_found="missing",
        )
        self.assertEqual((code, payload["Status"]), (200, "destroyed"))

        svc._get_for_action = AsyncMock(return_value=destroyed_row)
        payload, code = await svc._destroy(
            where={"id": active_row.id},
            auth_user_id=auth_user_id,
            data=SimpleNamespace(row_version=6, reason="ignored"),
            not_found="missing",
        )
        self.assertEqual((code, payload["Status"]), (200, "destroyed"))

        svc._get_for_action = AsyncMock(return_value=active_row)
        svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._destroy(
                where={"id": active_row.id},
                auth_user_id=auth_user_id,
                data=SimpleNamespace(row_version=4, reason="x"),
                not_found="missing",
            )
        self.assertEqual(ctx.exception.code, 500)

        svc._get_for_action = AsyncMock(return_value=active_row)
        svc.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc._destroy(
                where={"id": active_row.id},
                auth_user_id=auth_user_id,
                data=SimpleNamespace(row_version=4, reason="x"),
                not_found="missing",
            )
        self.assertEqual(ctx.exception.code, 409)

        svc._rotate = AsyncMock(return_value=({"ok": True}, 200))
        payload, code = await svc.entity_set_action_rotate(
            auth_user_id=auth_user_id,
            data=SimpleNamespace(tenant_id=None),
        )
        self.assertEqual((code, payload["ok"]), (200, True))
        svc._rotate.assert_awaited()

        payload, code = await svc.action_rotate(
            tenant_id=tenant_id,
            where={"tenant_id": tenant_id},
            auth_user_id=auth_user_id,
            data=SimpleNamespace(),
        )
        self.assertEqual(code, 200)

        svc._retire = AsyncMock(return_value=({"Status": "retired"}, 200))
        await svc.entity_action_retire(
            entity_id=uuid.uuid4(), auth_user_id=auth_user_id, data=SimpleNamespace()
        )
        await svc.action_retire(
            tenant_id=tenant_id,
            entity_id=uuid.uuid4(),
            where={},
            auth_user_id=auth_user_id,
            data=SimpleNamespace(),
        )

        svc._destroy = AsyncMock(return_value=({"Status": "destroyed"}, 200))
        await svc.entity_action_destroy(
            entity_id=uuid.uuid4(), auth_user_id=auth_user_id, data=SimpleNamespace()
        )
        await svc.action_destroy(
            tenant_id=tenant_id,
            entity_id=uuid.uuid4(),
            where={},
            auth_user_id=auth_user_id,
            data=SimpleNamespace(),
        )

        svc2 = KeyRefService(
            table="admin_key_ref",
            rsg=Mock(),
            key_material_resolver=Mock(),
        )
        svc2._activate = AsyncMock(
            return_value=KeyRefDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                purpose="audit_hmac",
                key_id="k",
                status="active",
            )
        )
        rotate_payload, rotate_status = await svc2._rotate(
            tenant_id=tenant_id,
            auth_user_id=auth_user_id,
            data=SimpleNamespace(
                purpose="audit_hmac",
                key_id="k",
                provider="local",
                secret_value=None,
                attributes=None,
            ),
        )
        self.assertEqual((rotate_status, rotate_payload["Status"]), (200, "active"))

        svc3 = KeyRefService(
            table="admin_key_ref",
            rsg=Mock(),
            key_material_resolver=Mock(),
            managed_key_material_cipher=Mock(
                encrypt=Mock(return_value="encrypted-managed")
            ),
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc3._rotate(
                tenant_id=tenant_id,
                auth_user_id=auth_user_id,
                data=SimpleNamespace(
                    purpose="audit_hmac",
                    key_id="k",
                    provider="managed",
                    secret_value=None,
                    attributes=None,
                ),
            )
        self.assertEqual(ctx.exception.code, 400)

    async def test_resolve_active_and_secret_precedence(self) -> None:
        tenant_id = uuid.uuid4()
        tenant_row = KeyRefDE(
            id=uuid.uuid4(), tenant_id=tenant_id, purpose="audit_hmac"
        )
        global_row = KeyRefDE(
            id=uuid.uuid4(),
            tenant_id=GLOBAL_TENANT_ID,
            purpose="audit_hmac",
        )

        resolver = Mock()
        resolver.resolve = Mock(
            return_value=ResolvedKeyMaterial(
                key_id="key-1",
                secret=b"secret",
                provider="local",
            )
        )

        svc = KeyRefService(
            table="admin_key_ref",
            rsg=Mock(),
            key_material_resolver=resolver,
        )
        svc._active_for_tenant = AsyncMock(side_effect=[tenant_row])
        resolved = await svc.resolve_active_for_purpose(
            tenant_id=tenant_id, purpose=" audit_hmac "
        )
        self.assertEqual(resolved.id, tenant_row.id)

        svc._active_for_tenant = AsyncMock(side_effect=[None, global_row])
        resolved = await svc.resolve_active_for_purpose(
            tenant_id=tenant_id, purpose="audit_hmac"
        )
        self.assertEqual(resolved.id, global_row.id)

        svc._active_for_tenant = AsyncMock(side_effect=[global_row])
        resolved = await svc.resolve_active_for_purpose(
            tenant_id=None, purpose="audit_hmac"
        )
        self.assertEqual(resolved.id, global_row.id)

        svc.resolve_active_for_purpose = AsyncMock(return_value=tenant_row)
        secret = await svc.resolve_secret_for_purpose(
            tenant_id=tenant_id, purpose="audit_hmac"
        )
        self.assertIsNotNone(secret)
        resolver.resolve.assert_called_once_with(tenant_row)

        svc.resolve_active_for_purpose = AsyncMock(return_value=None)
        self.assertIsNone(
            await svc.resolve_secret_for_purpose(
                tenant_id=tenant_id, purpose="audit_hmac"
            )
        )

        key_ref_id = uuid.uuid4()
        key_ref_by_id = KeyRefDE(
            id=key_ref_id,
            tenant_id=tenant_id,
            purpose="audit_hmac",
        )
        svc.get = AsyncMock(  # type: ignore[method-assign]
            side_effect=[key_ref_by_id, None]
        )
        secret = await svc.resolve_secret_for_id(
            tenant_id=tenant_id,
            key_ref_id=key_ref_id,
        )
        self.assertIsNotNone(secret)
        self.assertIsNone(
            await svc.resolve_secret_for_id(
                tenant_id=tenant_id,
                key_ref_id=key_ref_id,
            )
        )
        self.assertEqual(
            svc.get.await_args_list[0].args[0],
            {
                "tenant_id": tenant_id,
                "id": key_ref_id,
                "status": "active",
            },
        )

        resolver.resolve.reset_mock()
        tenant_key_row = KeyRefDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            purpose="audit_hmac",
            key_id="Audit-Key-Tenant",
            status="active",
            provider="local",
        )
        svc.list = AsyncMock(return_value=[tenant_key_row])
        resolved = await svc.resolve_secret_for_key_id(
            tenant_id=tenant_id,
            purpose="audit_hmac",
            key_id="audit-key-tenant",
        )
        self.assertIsNotNone(resolved)
        resolver.resolve.assert_called_once_with(tenant_key_row)

        resolver.resolve.reset_mock()
        global_retired = KeyRefDE(
            id=uuid.uuid4(),
            tenant_id=GLOBAL_TENANT_ID,
            purpose="audit_hmac",
            key_id="Audit-Key-Global",
            status="retired",
            provider="local",
        )
        svc.list = AsyncMock(side_effect=[[], [], [], [global_retired]])
        resolved = await svc.resolve_secret_for_key_id(
            tenant_id=tenant_id,
            purpose="audit_hmac",
            key_id="AUDIT-KEY-GLOBAL",
        )
        self.assertIsNotNone(resolved)
        resolver.resolve.assert_called_once_with(global_retired)

        resolver.resolve.reset_mock()
        destroyed = KeyRefDE(
            id=uuid.uuid4(),
            tenant_id=GLOBAL_TENANT_ID,
            purpose="audit_hmac",
            key_id="Destroyed-Key",
            status="destroyed",
            provider="local",
        )
        svc.list = AsyncMock(side_effect=[[destroyed], []])
        self.assertIsNone(
            await svc.resolve_secret_for_key_id(
                tenant_id=None,
                purpose="audit_hmac",
                key_id="destroyed-key",
            )
        )
        resolver.resolve.assert_not_called()

        resolver.resolve.reset_mock()
        svc.list = AsyncMock(
            side_effect=[
                [
                    KeyRefDE(
                        id=uuid.uuid4(),
                        tenant_id=GLOBAL_TENANT_ID,
                        purpose="audit_hmac",
                        key_id="other-key",
                        status="active",
                        provider="local",
                    )
                ],
                [],
            ]
        )
        self.assertIsNone(
            await svc.resolve_secret_for_key_id(
                tenant_id=None,
                purpose="audit_hmac",
                key_id="wanted-key",
            )
        )
        resolver.resolve.assert_not_called()

        svc.list = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc.resolve_secret_for_key_id(
                tenant_id=None,
                purpose="audit_hmac",
                key_id="wanted-key",
            )
        self.assertEqual(ctx.exception.code, 500)


class TestPluginCapabilityGrantService(unittest.IsolatedAsyncioTestCase):
    """Covers grant/revoke resolution and capability lookup precedence."""

    async def test_create_and_get_for_action_validation(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            PluginCapabilityGrantService._normalize_required_text(
                " ",
                field_name="PluginKey",
            )
        self.assertEqual(ctx.exception.code, 400)
        self.assertIsNone(PluginCapabilityGrantService._normalize_optional_text(None))
        self.assertFalse(
            PluginCapabilityGrantService._same_datetime(
                datetime(2026, 2, 25, 10, 0, tzinfo=timezone.utc),
                None,
            )
        )
        self.assertFalse(
            PluginCapabilityGrantService._same_datetime(
                None,
                datetime(2026, 2, 25, 10, 0, tzinfo=timezone.utc),
            )
        )

        svc = PluginCapabilityGrantService(
            table="admin_plugin_capability_grant", rsg=Mock()
        )
        created = PluginCapabilityGrantDE(
            id=uuid.uuid4(),
            tenant_id=GLOBAL_TENANT_ID,
            plugin_key="plugin",
            capabilities=["cap.read"],
        )

        with patch.object(
            IRelationalService,
            "create",
            new=AsyncMock(return_value=created),
        ) as base_create:
            result = await svc.create(
                {
                    "tenant_id": None,
                    "plugin_key": " plugin ",
                    "capabilities": [" CAP.Read ", "cap.read", "cap.write"],
                }
            )

        self.assertEqual(result.id, created.id)
        payload = base_create.await_args.args[0]
        self.assertEqual(payload["tenant_id"], GLOBAL_TENANT_ID)
        self.assertEqual(payload["plugin_key"], "plugin")
        self.assertEqual(payload["capabilities"], ["cap.read", "cap.write"])

        with self.assertRaises(HTTPException) as ctx:
            PluginCapabilityGrantService._normalize_capabilities("bad")
        self.assertEqual(ctx.exception.code, 400)
        with self.assertRaises(HTTPException) as ctx:
            PluginCapabilityGrantService._normalize_capabilities([" "])
        self.assertEqual(ctx.exception.code, 400)

        where = {"id": uuid.uuid4()}
        svc.get = AsyncMock(return_value=created)
        found = await svc._get_for_action(
            where=where, expected_row_version=1, not_found="x"
        )
        self.assertEqual(found.id, created.id)

        svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(
                where=where, expected_row_version=1, not_found="x"
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.get = AsyncMock(side_effect=[None, None])
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(
                where=where, expected_row_version=1, not_found="missing"
            )
        self.assertEqual(ctx.exception.code, 404)

        svc.get = AsyncMock(side_effect=[None, created])
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(
                where=where, expected_row_version=1, not_found="missing"
            )
        self.assertEqual(ctx.exception.code, 409)

        svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])
        with self.assertRaises(HTTPException) as ctx:
            await svc._get_for_action(
                where=where, expected_row_version=1, not_found="missing"
            )
        self.assertEqual(ctx.exception.code, 500)

    async def test_grant_revoke_and_resolution_paths(self) -> None:
        tenant_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        now = datetime(2026, 2, 25, 21, 0, tzinfo=timezone.utc)

        svc = PluginCapabilityGrantService(
            table="admin_plugin_capability_grant", rsg=Mock()
        )
        svc._now_utc = lambda: now

        current = PluginCapabilityGrantDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            plugin_key="com.vorsocomputing.mugen.audit",
            capabilities=["evidence.read"],
            expires_at=None,
            revoked_at=None,
            attributes={"x": 1},
            row_version=4,
        )

        svc.get = AsyncMock(return_value=current)
        payload, code = await svc._grant(
            tenant_id=tenant_id,
            auth_user_id=auth_user_id,
            data=SimpleNamespace(
                plugin_key="com.vorsocomputing.mugen.audit",
                capabilities=["evidence.read"],
                expires_at=None,
                attributes={"x": 1},
            ),
        )
        self.assertEqual((code, payload["Granted"]), (200, True))

        updated = PluginCapabilityGrantDE(
            id=current.id,
            tenant_id=tenant_id,
            plugin_key=current.plugin_key,
            capabilities=["evidence.read", "evidence.verify"],
            revoked_at=None,
            row_version=5,
        )
        svc.get = AsyncMock(return_value=current)
        svc.update = AsyncMock(return_value=updated)
        payload, code = await svc._grant(
            tenant_id=tenant_id,
            auth_user_id=auth_user_id,
            data=SimpleNamespace(
                plugin_key=current.plugin_key,
                capabilities=["evidence.read", "evidence.verify"],
                expires_at=None,
                attributes=None,
            ),
        )
        self.assertEqual((code, payload["PluginKey"]), (200, current.plugin_key))

        svc.update = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc._grant(
                tenant_id=tenant_id,
                auth_user_id=auth_user_id,
                data=SimpleNamespace(
                    plugin_key=current.plugin_key,
                    capabilities=["evidence.read", "evidence.verify"],
                    expires_at=None,
                    attributes=None,
                ),
            )
        self.assertEqual(ctx.exception.code, 409)

        svc.get = AsyncMock(return_value=None)
        created = PluginCapabilityGrantDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            plugin_key="plugin",
            capabilities=["a"],
        )
        svc.create = AsyncMock(return_value=created)
        payload, code = await svc._grant(
            tenant_id=tenant_id,
            auth_user_id=auth_user_id,
            data=SimpleNamespace(
                plugin_key="plugin",
                capabilities=["a"],
                expires_at=None,
                attributes=None,
            ),
        )
        self.assertEqual((code, payload["TenantId"]), (201, str(tenant_id)))

        svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._grant(
                tenant_id=tenant_id,
                auth_user_id=auth_user_id,
                data=SimpleNamespace(plugin_key="plugin", capabilities=["x"]),
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.get = AsyncMock(return_value=current)
        svc.update = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._grant(
                tenant_id=tenant_id,
                auth_user_id=auth_user_id,
                data=SimpleNamespace(
                    plugin_key=current.plugin_key,
                    capabilities=["other"],
                    expires_at=None,
                    attributes=None,
                ),
            )
        self.assertEqual(ctx.exception.code, 500)

        revoked = PluginCapabilityGrantDE(id=current.id, revoked_at=now, row_version=5)
        svc._get_for_action = AsyncMock(return_value=revoked)
        payload, code = await svc._revoke(
            where={"id": revoked.id},
            auth_user_id=auth_user_id,
            data=SimpleNamespace(row_version=5, reason="done"),
        )
        self.assertEqual((code, payload["Revoked"]), (200, True))

        svc._get_for_action = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=revoked)
        payload, code = await svc._revoke(
            where={"id": current.id},
            auth_user_id=auth_user_id,
            data=SimpleNamespace(row_version=4, reason="cleanup"),
        )
        self.assertEqual((code, payload["Revoked"]), (200, True))

        svc.update_with_row_version = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc._revoke(
                where={"id": current.id},
                auth_user_id=auth_user_id,
                data=SimpleNamespace(row_version=4, reason="cleanup"),
            )
        self.assertEqual(ctx.exception.code, 409)

        svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc._revoke(
                where={"id": current.id},
                auth_user_id=auth_user_id,
                data=SimpleNamespace(row_version=4, reason="cleanup"),
            )
        self.assertEqual(ctx.exception.code, 500)

        svc._grant = AsyncMock(return_value=({"ok": True}, 200))
        await svc.entity_set_action_grant(
            auth_user_id=auth_user_id, data=SimpleNamespace(tenant_id=None)
        )
        await svc.action_grant(
            tenant_id=tenant_id,
            where={},
            auth_user_id=auth_user_id,
            data=SimpleNamespace(),
        )

        svc._revoke = AsyncMock(return_value=({"Revoked": True}, 200))
        await svc.entity_action_revoke(
            entity_id=uuid.uuid4(), auth_user_id=auth_user_id, data=SimpleNamespace()
        )
        await svc.action_revoke(
            tenant_id=tenant_id,
            entity_id=uuid.uuid4(),
            where={},
            auth_user_id=auth_user_id,
            data=SimpleNamespace(),
        )

        self.assertTrue(
            PluginCapabilityGrantService._same_datetime(
                datetime(2026, 2, 25, 10, 0),
                datetime(2026, 2, 25, 10, 0, tzinfo=timezone.utc),
            )
        )
        self.assertFalse(
            PluginCapabilityGrantService._same_datetime(
                datetime(2026, 2, 25, 10, 0, tzinfo=timezone.utc),
                datetime(2026, 2, 25, 11, 0, tzinfo=timezone.utc),
            )
        )
        self.assertFalse(
            PluginCapabilityGrantService._same_datetime(
                datetime(2026, 2, 25, 10, 0, tzinfo=timezone.utc),
                datetime(2026, 2, 25, 11, 0),
            )
        )
        self.assertTrue(
            PluginCapabilityGrantService._is_expired(
                PluginCapabilityGrantDE(expires_at=datetime(2026, 2, 25, 9, 59)),
                now=datetime(2026, 2, 25, 10, 0, tzinfo=timezone.utc),
            )
        )
        self.assertFalse(
            PluginCapabilityGrantService._is_expired(
                PluginCapabilityGrantDE(expires_at=None),
                now=datetime(2026, 2, 25, 10, 0, tzinfo=timezone.utc),
            )
        )

        tenant_grant = PluginCapabilityGrantDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            plugin_key="plugin",
            capabilities=["cap.a"],
            revoked_at=None,
        )
        global_grant = PluginCapabilityGrantDE(
            id=uuid.uuid4(),
            tenant_id=GLOBAL_TENANT_ID,
            plugin_key="plugin",
            capabilities=["cap.b"],
            revoked_at=None,
        )

        svc._resolve_for_tenant = AsyncMock(side_effect=[tenant_grant])
        granted, source_tid, source_grant = await svc.resolve_capability(
            tenant_id=tenant_id,
            plugin_key="plugin",
            capability="cap.a",
        )
        self.assertTrue(granted)
        self.assertEqual(source_tid, tenant_id)
        self.assertEqual(source_grant.id, tenant_grant.id)

        svc._resolve_for_tenant = AsyncMock(side_effect=[tenant_grant])
        granted, source_tid, _ = await svc.resolve_capability(
            tenant_id=tenant_id,
            plugin_key="plugin",
            capability="cap.missing",
        )
        self.assertFalse(granted)
        self.assertEqual(source_tid, tenant_id)

        svc._resolve_for_tenant = AsyncMock(side_effect=[None, global_grant])
        granted, source_tid, source_grant = await svc.resolve_capability(
            tenant_id=tenant_id,
            plugin_key="plugin",
            capability="cap.b",
        )
        self.assertTrue(granted)
        self.assertEqual(source_tid, GLOBAL_TENANT_ID)
        self.assertEqual(source_grant.id, global_grant.id)

        svc._resolve_for_tenant = AsyncMock(side_effect=[None, None])
        granted, source_tid, source_grant = await svc.resolve_capability(
            tenant_id=tenant_id,
            plugin_key="plugin",
            capability="cap.none",
        )
        self.assertFalse(granted)
        self.assertIsNone(source_tid)
        self.assertIsNone(source_grant)

        svc._resolve_for_tenant = AsyncMock(side_effect=[global_grant])
        granted, source_tid, source_grant = await svc.resolve_capability(
            tenant_id=GLOBAL_TENANT_ID,
            plugin_key="plugin",
            capability="cap.b",
        )
        self.assertTrue(granted)
        self.assertEqual(source_tid, GLOBAL_TENANT_ID)
        self.assertEqual(source_grant.id, global_grant.id)

        svc3 = PluginCapabilityGrantService(
            table="admin_plugin_capability_grant",
            rsg=Mock(),
        )
        svc3._now_utc = lambda: now
        svc3.get = AsyncMock(return_value=None)
        self.assertIsNone(
            await svc3._resolve_for_tenant(tenant_id=tenant_id, plugin_key="plugin")
        )
        svc3.get = AsyncMock(
            return_value=PluginCapabilityGrantDE(
                id=uuid.uuid4(),
                plugin_key="plugin",
                revoked_at=None,
                expires_at=now + timedelta(seconds=5),
                capabilities=["cap"],
            )
        )
        self.assertIsNotNone(
            await svc3._resolve_for_tenant(tenant_id=tenant_id, plugin_key="plugin")
        )

        svc2 = PluginCapabilityGrantService(
            table="admin_plugin_capability_grant",
            rsg=Mock(),
        )
        svc2.get = AsyncMock(
            return_value=PluginCapabilityGrantDE(
                id=uuid.uuid4(),
                plugin_key="plugin",
                revoked_at=None,
                expires_at=now - timedelta(seconds=1),
                capabilities=["cap"],
            )
        )
        self.assertIsNone(
            await svc2._resolve_for_tenant(tenant_id=tenant_id, plugin_key="plugin")
        )

"""Unit tests for ACP runtime config profile service helpers."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from werkzeug.exceptions import HTTPException

from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.constants import GLOBAL_TENANT_ID
from mugen.core.plugin.acp.domain import RuntimeConfigProfileDE
from mugen.core.plugin.acp.service import runtime_config_profile as runtime_mod

_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000111")
_PROFILE_ID = uuid.UUID("00000000-0000-0000-0000-000000000222")


def _profile(
    *,
    profile_id: uuid.UUID = _PROFILE_ID,
    tenant_id: uuid.UUID = _TENANT_ID,
    category: str = "messaging.platform_defaults",
    profile_key: str = "matrix",
    display_name: str | None = "Matrix Defaults",
    is_active: bool = True,
    settings_json: dict | None = None,
    attributes: dict | None = None,
) -> RuntimeConfigProfileDE:
    return RuntimeConfigProfileDE(
        id=profile_id,
        tenant_id=tenant_id,
        category=category,
        profile_key=profile_key,
        display_name=display_name,
        is_active=is_active,
        settings_json=dict(settings_json or {}),
        attributes=None if attributes is None else dict(attributes),
    )


def _service() -> runtime_mod.RuntimeConfigProfileService:
    return runtime_mod.RuntimeConfigProfileService(
        table="admin_runtime_config_profile",
        rsg=Mock(),
    )


class TestRuntimeConfigProfileService(unittest.IsolatedAsyncioTestCase):
    """Covers normalization, fallback, and reload paths for runtime profiles."""

    async def test_normalization_and_reload_guard_helpers(self) -> None:
        svc = _service()

        self.assertEqual(
            svc._normalize_tenant_id(None),  # pylint: disable=protected-access
            GLOBAL_TENANT_ID,
        )
        self.assertEqual(
            svc._normalize_tenant_id(str(_TENANT_ID)),  # pylint: disable=protected-access
            _TENANT_ID,
        )
        self.assertIsNone(
            svc._normalize_optional_text(123)  # pylint: disable=protected-access
        )
        self.assertEqual(
            svc._normalize_attributes({"Tag": "value"}),  # pylint: disable=protected-access
            {"Tag": "value"},
        )

        with self.assertRaisesRegex(RuntimeError, "TenantId must be a valid UUID"):
            svc._normalize_tenant_id("not-a-uuid")  # pylint: disable=protected-access

        with (
            patch.object(
                runtime_mod.di,
                "container",
                new=SimpleNamespace(build=Mock(side_effect=RuntimeError("boom"))),
            ),
            patch.object(
                runtime_mod,
                "reload_platform_runtime_profiles",
                new=AsyncMock(),
            ) as reload_runtime,
        ):
            await svc._reload_runtime_profiles_for_category(  # pylint: disable=protected-access
                category="messaging.platform_defaults",
                profile_key="matrix",
            )
        reload_runtime.assert_not_awaited()

        with (
            patch.object(
                runtime_mod.di,
                "container",
                new=SimpleNamespace(build=Mock(return_value="injector")),
            ),
            patch.object(
                runtime_mod,
                "reload_platform_runtime_profiles",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
        ):
            await svc._reload_runtime_profiles_for_category(  # pylint: disable=protected-access
                category="messaging.platform_defaults",
                profile_key="matrix",
            )

        with patch.object(
            runtime_mod,
            "reload_platform_runtime_profiles",
            new=AsyncMock(),
        ) as reload_runtime:
            await svc._reload_runtime_profiles_for_category(  # pylint: disable=protected-access
                category="ops_connector.defaults",
                profile_key="default",
            )
        reload_runtime.assert_not_awaited()

    async def test_create_normalizes_and_reloads_messaging_profiles(self) -> None:
        svc = _service()
        created = _profile(
            tenant_id=GLOBAL_TENANT_ID,
            settings_json={"client": {"device": "default-device"}},
            attributes={"Tag": "value"},
        )

        with (
            patch.object(
                IRelationalService,
                "create",
                new=AsyncMock(return_value=created),
            ) as base_create,
            patch.object(
                runtime_mod.di,
                "container",
                new=SimpleNamespace(build=Mock(return_value="injector")),
            ),
            patch.object(
                runtime_mod,
                "reload_platform_runtime_profiles",
                new=AsyncMock(),
            ) as reload_runtime,
        ):
            result = await svc.create(
                {
                    "tenant_id": None,
                    "category": " Messaging.Platform_Defaults ",
                    "profile_key": " MATRIX ",
                    "display_name": " Matrix Defaults ",
                    "settings_json": {"client": {"device": "default-device"}},
                    "attributes": {"Tag": "value"},
                }
            )

        self.assertEqual(result.id, created.id)
        self.assertEqual(
            base_create.await_args.args[0],
            {
                "tenant_id": GLOBAL_TENANT_ID,
                "category": "messaging.platform_defaults",
                "profile_key": "matrix",
                "display_name": "Matrix Defaults",
                "is_active": True,
                "settings_json": {"client": {"device": "default-device"}},
                "attributes": {"Tag": "value"},
            },
        )
        reload_runtime.assert_awaited_once_with(
            injector="injector",
            platforms=("matrix",),
        )

    async def test_create_accepts_ops_connector_defaults_without_reload(self) -> None:
        svc = _service()
        created = _profile(
            category="ops_connector.defaults",
            profile_key="default",
            settings_json={"timeout_seconds_default": 12.5},
        )

        with (
            patch.object(
                IRelationalService,
                "create",
                new=AsyncMock(return_value=created),
            ) as base_create,
            patch.object(
                runtime_mod.di,
                "container",
                new=SimpleNamespace(build=Mock(return_value="injector")),
            ),
            patch.object(
                runtime_mod,
                "reload_platform_runtime_profiles",
                new=AsyncMock(),
            ) as reload_runtime,
        ):
            await svc.create(
                {
                    "tenant_id": _TENANT_ID,
                    "category": "ops_connector.defaults",
                    "profile_key": "default",
                    "settings_json": {"timeout_seconds_default": 12.5},
                }
            )

        self.assertEqual(
            base_create.await_args.args[0]["settings_json"],
            {"timeout_seconds_default": 12.5},
        )
        reload_runtime.assert_not_awaited()

    async def test_create_rejects_invalid_category_profile_and_settings(self) -> None:
        svc = _service()

        with self.assertRaises(HTTPException) as ctx:
            await svc.create(
                {
                    "tenant_id": _TENANT_ID,
                    "category": "unsupported",
                    "profile_key": "x",
                    "settings_json": {},
                }
            )
        self.assertEqual(ctx.exception.code, 400)
        self.assertIn("Category must be one of", str(ctx.exception))

        with self.assertRaises(HTTPException) as ctx:
            await svc.create(
                {
                    "tenant_id": _TENANT_ID,
                    "category": "ops_connector.defaults",
                    "profile_key": "tenant-a",
                    "settings_json": {},
                }
            )
        self.assertEqual(ctx.exception.code, 400)
        self.assertIn("ProfileKey must be 'default'", str(ctx.exception))

        with self.assertRaises(HTTPException) as ctx:
            await svc.create(
                {
                    "tenant_id": _TENANT_ID,
                    "category": "messaging.platform_defaults",
                    "profile_key": "telegram",
                    "settings_json": {"webhook": {"path_token": "bad"}},
                }
            )
        self.assertEqual(ctx.exception.code, 400)
        self.assertIn("SettingsJson path 'webhook.path_token'", str(ctx.exception))

        with self.assertRaises(HTTPException) as ctx:
            await svc.create(
                {
                    "tenant_id": _TENANT_ID,
                    "category": "ops_connector.defaults",
                    "profile_key": "default",
                    "settings_json": {},
                    "attributes": [],
                }
            )
        self.assertEqual(ctx.exception.code, 400)
        self.assertIn("Attributes must be a JSON object", str(ctx.exception))

    async def test_update_and_update_with_row_version_normalize_payload(self) -> None:
        svc = _service()
        current = _profile(
            settings_json={"client": {"device": "default-device"}},
        )
        updated = _profile(
            settings_json={"client": {"device": "new-device"}},
        )
        svc.get = AsyncMock(side_effect=[current, current])  # type: ignore[method-assign]

        with patch.object(
            IRelationalService,
            "update",
            new=AsyncMock(return_value=updated),
        ) as base_update:
            result = await svc.update(
                {"id": _PROFILE_ID},
                {
                    "display_name": " Updated ",
                    "settings_json": {"client": {"device": "new-device"}},
                },
            )
        self.assertEqual(result, updated)
        self.assertEqual(
            base_update.await_args.args[1],
            {
                "tenant_id": _TENANT_ID,
                "category": "messaging.platform_defaults",
                "profile_key": "matrix",
                "display_name": "Updated",
                "is_active": True,
                "settings_json": {"client": {"device": "new-device"}},
                "attributes": None,
            },
        )

        with patch.object(
            IRelationalService,
            "update_with_row_version",
            new=AsyncMock(return_value=updated),
        ) as base_update_with_rv:
            result = await svc.update_with_row_version(
                {"id": _PROFILE_ID},
                expected_row_version=5,
                changes={
                    "settings_json": {"client": {"device": "new-device"}},
                    "attributes": {"Tag": "value"},
                },
            )
        self.assertEqual(result, updated)
        self.assertEqual(
            base_update_with_rv.await_args.kwargs["changes"],
            {
                "tenant_id": _TENANT_ID,
                "category": "messaging.platform_defaults",
                "profile_key": "matrix",
                "display_name": "Matrix Defaults",
                "is_active": True,
                "settings_json": {"client": {"device": "new-device"}},
                "attributes": {"Tag": "value"},
            },
        )

    async def test_update_paths_abort_400_for_invalid_payload(self) -> None:
        svc = _service()
        current = _profile()

        svc.get = AsyncMock(return_value=current)  # type: ignore[method-assign]
        with self.assertRaises(HTTPException) as ctx:
            await svc.update(
                {"id": _PROFILE_ID},
                {
                    "settings_json": {
                        "webhook": {
                            "path_token": "blocked",
                        }
                    }
                },
            )
        self.assertEqual(ctx.exception.code, 400)
        self.assertIn("SettingsJson path 'webhook.path_token'", str(ctx.exception))

        svc.get = AsyncMock(return_value=current)  # type: ignore[method-assign]
        with self.assertRaises(HTTPException) as ctx:
            await svc.update_with_row_version(
                {"id": _PROFILE_ID},
                expected_row_version=5,
                changes={
                    "settings_json": {
                        "webhook": {
                            "path_token": "blocked",
                        }
                    }
                },
            )
        self.assertEqual(ctx.exception.code, 400)
        self.assertIn("SettingsJson path 'webhook.path_token'", str(ctx.exception))

    async def test_update_paths_return_none_without_reload(self) -> None:
        svc = _service()
        svc.get = AsyncMock(side_effect=[None, _profile(), None, _profile()])  # type: ignore[method-assign]

        with (
            patch.object(
                IRelationalService,
                "update",
                new=AsyncMock(return_value=None),
            ) as base_update,
            patch.object(
                IRelationalService,
                "update_with_row_version",
                new=AsyncMock(return_value=None),
            ) as base_update_with_rv,
            patch.object(
                runtime_mod,
                "reload_platform_runtime_profiles",
                new=AsyncMock(),
            ) as reload_runtime,
        ):
            self.assertIsNone(await svc.update({"id": _PROFILE_ID}, {"display_name": "x"}))
            self.assertIsNone(
                await svc.update(
                    {"id": _PROFILE_ID},
                    {"display_name": "x"},
                )
            )
            self.assertIsNone(
                await svc.update_with_row_version(
                    {"id": _PROFILE_ID},
                    expected_row_version=1,
                    changes={"display_name": "x"},
                )
            )
            self.assertIsNone(
                await svc.update_with_row_version(
                    {"id": _PROFILE_ID},
                    expected_row_version=1,
                    changes={"display_name": "x"},
                )
            )

        base_update.assert_awaited_once()
        base_update_with_rv.assert_awaited_once()
        reload_runtime.assert_not_awaited()

    async def test_resolve_active_profile_and_settings_fallback(self) -> None:
        svc = _service()
        tenant_row = _profile(
            tenant_id=_TENANT_ID,
            settings_json={"timeout_seconds_default": 5.0},
            category="ops_connector.defaults",
            profile_key="default",
        )
        global_row = _profile(
            tenant_id=GLOBAL_TENANT_ID,
            settings_json={"timeout_seconds_default": 7.0},
            category="ops_connector.defaults",
            profile_key="default",
        )

        svc.get = AsyncMock(  # type: ignore[method-assign]
            side_effect=[tenant_row]
        )
        resolved = await svc.resolve_active_profile(
            tenant_id=_TENANT_ID,
            category="ops_connector.defaults",
            profile_key="default",
        )
        self.assertEqual(resolved.id, tenant_row.id)

        svc.get = AsyncMock(  # type: ignore[method-assign]
            side_effect=[None, global_row]
        )
        resolved = await svc.resolve_active_settings(
            tenant_id=_TENANT_ID,
            category="ops_connector.defaults",
            profile_key="default",
        )
        self.assertEqual(resolved, {"timeout_seconds_default": 7.0})

        svc.get = AsyncMock(return_value=None)  # type: ignore[method-assign]
        self.assertEqual(
            await svc.resolve_active_settings(
                tenant_id=_TENANT_ID,
                category="ops_connector.defaults",
                profile_key="default",
            ),
            {},
        )

    async def test_resolve_active_profile_global_lookup(self) -> None:
        svc = _service()
        global_row = _profile(
            tenant_id=GLOBAL_TENANT_ID,
            settings_json={"client": {"device": "global-default"}},
        )
        svc.get = AsyncMock(return_value=global_row)  # type: ignore[method-assign]

        resolved = await svc.resolve_active_profile(
            tenant_id=None,
            category="messaging.platform_defaults",
            profile_key="matrix",
        )

        self.assertEqual(resolved.id, global_row.id)
        self.assertEqual(svc.get.await_count, 1)
        self.assertEqual(
            svc.get.await_args.args[0],
            {
                "tenant_id": GLOBAL_TENANT_ID,
                "category": "messaging.platform_defaults",
                "profile_key": "matrix",
                "is_active": True,
            },
        )


if __name__ == "__main__":
    unittest.main()

"""Unit tests for ACP messaging client profile service helpers."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from werkzeug.exceptions import HTTPException

from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.constants import GLOBAL_TENANT_ID
from mugen.core.plugin.acp.contract.service.key_provider import ResolvedKeyMaterial
from mugen.core.plugin.acp.domain import MessagingClientProfileDE
from mugen.core.plugin.acp.service import messaging_client_profile as profile_mod

_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000111")
_PROFILE_ID = uuid.UUID("00000000-0000-0000-0000-000000000222")
_SECONDARY_PROFILE_ID = uuid.UUID("00000000-0000-0000-0000-000000000333")
_KEY_REF_ID = uuid.UUID("00000000-0000-0000-0000-000000000444")


def _profile(
    *,
    client_profile_id: uuid.UUID = _PROFILE_ID,
    tenant_id: uuid.UUID = _TENANT_ID,
    platform_key: str = "line",
    profile_key: str = "support",
    display_name: str | None = "Support",
    is_active: bool = True,
    settings: dict | None = None,
    secret_refs: dict[str, str] | None = None,
    path_token: str | None = "line-path",
    recipient_user_id: str | None = None,
    account_number: str | None = None,
    phone_number_id: str | None = None,
    provider: str | None = None,
) -> MessagingClientProfileDE:
    return MessagingClientProfileDE(
        id=client_profile_id,
        tenant_id=tenant_id,
        platform_key=platform_key,
        profile_key=profile_key,
        display_name=display_name,
        is_active=is_active,
        settings=dict(settings or {}),
        secret_refs=dict(secret_refs or {}),
        path_token=path_token,
        recipient_user_id=recipient_user_id,
        account_number=account_number,
        phone_number_id=phone_number_id,
        provider=provider,
    )


def _make_service() -> tuple[
    profile_mod.MessagingClientProfileService,
    SimpleNamespace,
]:
    key_ref_service = SimpleNamespace(
        get=AsyncMock(),
        resolve_secret_for_id=AsyncMock(),
    )
    runtime_config_profile_service = SimpleNamespace(
        resolve_active_settings=AsyncMock(return_value={}),
    )
    svc = profile_mod.MessagingClientProfileService(
        table="admin_messaging_client_profile",
        rsg=Mock(),
        key_ref_service=key_ref_service,
        runtime_config_profile_service=runtime_config_profile_service,
    )
    return svc, key_ref_service


class TestMessagingClientProfileService(unittest.IsolatedAsyncioTestCase):
    """Covers normalization, runtime config, and CRUD lifecycle helpers."""

    async def test_normalization_helpers_and_reload_paths(self) -> None:
        svc, _ = _make_service()

        self.assertEqual(
            profile_mod.MessagingClientProfileService._normalize_tenant_id(None),
            GLOBAL_TENANT_ID,
        )
        self.assertEqual(
            profile_mod.MessagingClientProfileService._normalize_tenant_id(
                str(_TENANT_ID)
            ),
            _TENANT_ID,
        )
        with self.assertRaisesRegex(RuntimeError, "TenantId must be a valid UUID"):
            profile_mod.MessagingClientProfileService._normalize_tenant_id("bad")

        self.assertIsNone(
            profile_mod.MessagingClientProfileService._normalize_optional_text(None)
        )
        self.assertEqual(
            profile_mod.MessagingClientProfileService._normalize_optional_text(
                " line "
            ),
            "line",
        )
        with self.assertRaisesRegex(RuntimeError, "ProfileKey must be non-empty"):
            profile_mod.MessagingClientProfileService._normalize_required_text(
                " ",
                field_name="ProfileKey",
            )

        self.assertEqual(
            profile_mod.MessagingClientProfileService._normalize_mapping(None),
            {},
        )
        self.assertEqual(
            profile_mod.MessagingClientProfileService._normalize_mapping({"a": 1}),
            {"a": 1},
        )
        with self.assertRaisesRegex(RuntimeError, "Expected a JSON object payload"):
            profile_mod.MessagingClientProfileService._normalize_mapping([])

        raw_namespace = SimpleNamespace(dict={"raw": {"value": 1}})
        nested_namespace = SimpleNamespace(
            settings=SimpleNamespace(token="abc"),
            values=[SimpleNamespace(name="one"), {"two": 2}],
        )
        skipped_namespace = SimpleNamespace(dict=None, keep="value")
        setattr(skipped_namespace, "hidden__", "skip")
        self.assertEqual(
            profile_mod.MessagingClientProfileService._plain_data(raw_namespace),
            {"raw": {"value": 1}},
        )
        self.assertEqual(
            profile_mod.MessagingClientProfileService._plain_data(nested_namespace),
            {
                "settings": {"token": "abc"},
                "values": [{"name": "one"}, {"two": 2}],
            },
        )
        self.assertEqual(
            profile_mod.MessagingClientProfileService._plain_data(skipped_namespace),
            {"keep": "value"},
        )

        self.assertEqual(
            profile_mod.MessagingClientProfileService._deep_merge(
                {"channel": {"secret": "old"}, "other": 1},
                {"channel": {"secret": "new"}},
            ),
            {"channel": {"secret": "new"}, "other": 1},
        )
        payload: dict[str, object] = {}
        profile_mod.MessagingClientProfileService._set_nested(
            payload,
            ("webhook", "path_token"),
            "line-path",
        )
        self.assertEqual(payload, {"webhook": {"path_token": "line-path"}})
        profile_mod.MessagingClientProfileService._delete_nested(
            payload,
            ("webhook", "path_token"),
        )
        self.assertEqual(payload, {})
        payload = {"webhook": "skip"}
        profile_mod.MessagingClientProfileService._delete_nested(
            payload,
            ("webhook", "path_token"),
        )
        self.assertEqual(payload, {"webhook": "skip"})

        self.assertEqual(
            profile_mod.MessagingClientProfileService._normalize_platform_key(
                " LINE "
            ),
            "line",
        )
        with self.assertRaisesRegex(RuntimeError, "PlatformKey must be one of"):
            profile_mod.MessagingClientProfileService._normalize_platform_key("web")

        self.assertEqual(
            profile_mod.MessagingClientProfileService._normalize_secret_refs(
                {"channel.secret": str(_KEY_REF_ID)}
            ),
            {"channel.secret": str(_KEY_REF_ID)},
        )
        self.assertEqual(
            profile_mod.MessagingClientProfileService._normalize_settings(
                platform_key="matrix",
                value={"client": {"device": "dev-box"}},
            ),
            {"client": {"device": "dev-box"}},
        )
        self.assertEqual(
            profile_mod.MessagingClientProfileService._normalize_platform_secret_refs(
                platform_key="line",
                value={"channel.secret": str(_KEY_REF_ID)},
            ),
            {"channel.secret": str(_KEY_REF_ID)},
        )
        with self.assertRaisesRegex(RuntimeError, "SecretRefs.bad must be a valid"):
            profile_mod.MessagingClientProfileService._normalize_secret_refs(
                {"bad": "not-a-uuid"}
            )
        with self.assertRaisesRegex(RuntimeError, "Settings path 'channel.mode'"):
            profile_mod.MessagingClientProfileService._normalize_settings(
                platform_key="line",
                value={"channel": {"mode": "reply"}},
            )
        with self.assertRaisesRegex(
            RuntimeError,
            "SecretRefs path 'client.password' is not allowed",
        ):
            profile_mod.MessagingClientProfileService._normalize_platform_secret_refs(
                platform_key="line",
                value={"client.password": str(_KEY_REF_ID)},
            )

        identifier_payload = {
            "path_token": " line-path ",
            "recipient_user_id": " user-1 ",
            "account_number": " +15550000001 ",
            "phone_number_id": " phone-1 ",
            "provider": " official_account ",
        }
        svc._normalize_identifier_fields(
            payload=identifier_payload,
            platform_key="line",
        )
        self.assertEqual(identifier_payload["path_token"], "line-path")
        self.assertEqual(identifier_payload["provider"], "official_account")
        with self.assertRaisesRegex(RuntimeError, "path_token is required"):
            svc._normalize_identifier_fields(
                payload={"path_token": " "},
                platform_key="line",
            )

        delegate_svc, _ = _make_service()
        delegate_svc._reload_runtime_profiles_for_platforms = (
            AsyncMock()  # type: ignore[method-assign]
        )
        # pylint: disable=protected-access
        await delegate_svc._reload_runtime_profiles()
        (
            delegate_svc._reload_runtime_profiles_for_platforms
            .assert_awaited_once_with()
        )  # type: ignore[union-attr]

        with patch.object(
            profile_mod.di,
            "container",
            new=SimpleNamespace(build=Mock(side_effect=RuntimeError("no-di"))),
        ):
            # pylint: disable=protected-access
            await svc._reload_runtime_profiles_for_platforms("line")

        with (
            patch.object(
                profile_mod.di,
                "container",
                new=SimpleNamespace(build=Mock(return_value="injector")),
            ),
            patch.object(
                profile_mod,
                "reload_platform_runtime_profiles",
                new=AsyncMock(),
            ) as reload_runtime,
        ):
            # pylint: disable=protected-access
            await svc._reload_runtime_profiles_for_platforms(
                " line ",
                "invalid",
                "line",
                "telegram",
            )
        reload_runtime.assert_awaited_once_with(
            injector="injector",
            platforms=("line", "telegram"),
        )

        with (
            patch.object(
                profile_mod.di,
                "container",
                new=SimpleNamespace(build=Mock(return_value="injector")),
            ),
            patch.object(
                profile_mod,
                "reload_platform_runtime_profiles",
                new=AsyncMock(side_effect=RuntimeError("reload failed")),
            ),
        ):
            # pylint: disable=protected-access
            await svc._reload_runtime_profiles_for_platforms("line")

    async def test_secret_validation_snapshot_and_secret_resolution(self) -> None:
        svc, key_ref_service = _make_service()

        key_ref_service.get = AsyncMock(
            return_value=SimpleNamespace(id=_KEY_REF_ID)
        )
        await svc._validate_secret_refs(  # pylint: disable=protected-access
            tenant_id=_TENANT_ID,
            secret_refs={"channel.secret": str(_KEY_REF_ID)},
        )

        key_ref_service.get = AsyncMock(return_value=None)
        with self.assertRaisesRegex(RuntimeError, "active KeyRefs in the same tenant"):
            await svc._validate_secret_refs(  # pylint: disable=protected-access
                tenant_id=_TENANT_ID,
                secret_refs={"channel.secret": str(_KEY_REF_ID)},
            )

        profile = _profile(
            platform_key="wechat",
            profile_key="official",
            settings={"provider": "official_account"},
            secret_refs={"channel.secret": str(_KEY_REF_ID)},
            path_token="wechat-path",
            provider="official_account",
        )
        self.assertEqual(
            svc._snapshot_for_runtime(profile),  # pylint: disable=protected-access
            {
                "id": str(_PROFILE_ID),
                "tenant_id": str(_TENANT_ID),
                "platform_key": "wechat",
                "profile_key": "official",
                "display_name": "Support",
                "is_active": True,
                "settings": {"provider": "official_account"},
                "secret_refs": {"channel.secret": str(_KEY_REF_ID)},
                "path_token": "wechat-path",
                "recipient_user_id": None,
                "account_number": None,
                "phone_number_id": None,
                "provider": "official_account",
            },
        )

        key_ref_service.resolve_secret_for_id = AsyncMock(
            return_value=ResolvedKeyMaterial(
                key_id="key-1",
                secret=b"secret-value",
                provider="local",
            )
        )
        self.assertEqual(
            await svc._resolve_secret_value(  # pylint: disable=protected-access
                tenant_id=_TENANT_ID,
                key_ref_id=str(_KEY_REF_ID),
            ),
            "secret-value",
        )

        key_ref_service.resolve_secret_for_id = AsyncMock(return_value=None)
        with self.assertRaisesRegex(RuntimeError, "Unable to resolve KeyRef secret"):
            await svc._resolve_secret_value(  # pylint: disable=protected-access
                tenant_id=_TENANT_ID,
                key_ref_id=str(_KEY_REF_ID),
            )

    async def test_build_runtime_platform_section_and_config(self) -> None:
        svc, _ = _make_service()
        client_profile = _profile(
            platform_key="line",
            profile_key="support",
            settings={},
            secret_refs={
                " ": str(_KEY_REF_ID),
                "channel.secret": str(_KEY_REF_ID),
            },
            path_token="line-path",
        )
        svc._resolve_secret_value = AsyncMock(  # type: ignore[method-assign]
            return_value="resolved-secret"
        )

        with self.assertRaisesRegex(TypeError, "Configuration root must be a mapping"):
            await svc.build_runtime_platform_section(
                config=[],
                client_profile=client_profile,
            )

        section = await svc.build_runtime_platform_section(
            config=profile_mod.build_config_namespace(
                {
                    "line": {
                        "server": {"bind": "0.0.0.0"},
                        "profiles": [{"key": "legacy"}],
                    }
                }
            ),
            client_profile=client_profile,
        )
        self.assertEqual(section["server"]["bind"], "0.0.0.0")
        self.assertEqual(section["channel"]["secret"], "resolved-secret")
        self.assertEqual(section["webhook"]["path_token"], "line-path")
        self.assertEqual(section["key"], "support")
        self.assertEqual(section["client_profile_id"], str(_PROFILE_ID))
        self.assertEqual(section["client_profile_key"], "support")
        self.assertNotIn("profiles", section)

        matrix_section = await svc.build_runtime_platform_section(
            config={
                "matrix": {
                    "assistant": {"name": "Legacy Root Name"},
                    "profile_displayname": "legacy-root-name",
                }
            },
            client_profile=_profile(
                platform_key="matrix",
                profile_key="default",
                display_name="Profile Display Name",
                settings={
                    "assistant": {"name": "settings-name"},
                    "profile_displayname": "settings-display-name",
                    "client": {"device": "device-default"},
                },
                secret_refs={},
                path_token=None,
                recipient_user_id="@bot:example.com",
            ),
        )
        self.assertEqual(matrix_section["client"]["user"], "@bot:example.com")
        self.assertEqual(matrix_section["client"]["device"], "device-default")
        self.assertEqual(
            matrix_section["profile_displayname"],
            "Profile Display Name",
        )
        self.assertNotIn("assistant", matrix_section)

        matrix_section_without_display_name = await svc.build_runtime_platform_section(
            config={
                "matrix": {
                    "assistant": {"name": "Legacy Root Name"},
                    "profile_displayname": "legacy-root-name",
                }
            },
            client_profile=_profile(
                platform_key="matrix",
                profile_key="default",
                display_name=None,
                settings={
                    "assistant": {"name": "settings-name"},
                    "profile_displayname": "settings-display-name",
                    "client": {"device": "device-default"},
                },
                secret_refs={},
                path_token=None,
                recipient_user_id="@bot:example.com",
            ),
        )
        self.assertEqual(
            matrix_section_without_display_name["client"]["user"],
            "@bot:example.com",
        )
        self.assertNotIn("assistant", matrix_section_without_display_name)
        self.assertNotIn(
            "profile_displayname",
            matrix_section_without_display_name,
        )

        wechat_section = await svc.build_runtime_platform_section(
            config={"wechat": {}},
            client_profile=_profile(
                platform_key="wechat",
                profile_key="official",
                settings={},
                secret_refs={},
                path_token="wechat-path",
                provider=None,
            ),
        )
        self.assertEqual(wechat_section["webhook"]["path_token"], "wechat-path")
        self.assertNotIn("provider", wechat_section)

        with self.assertRaisesRegex(TypeError, "Configuration root must be a mapping"):
            await svc.build_runtime_config(
                config=[],
                client_profile=client_profile,
            )

        runtime_config = await svc.build_runtime_config(
            config={"mugen": {"platforms": ["line"]}},
            client_profile=client_profile,
        )
        self.assertEqual(runtime_config.line.channel.secret, "resolved-secret")
        self.assertEqual(runtime_config.line.webhook.path_token, "line-path")
        self.assertEqual(runtime_config.line.client_profile_id, str(_PROFILE_ID))

    async def test_runtime_spec_and_lookup_helpers(self) -> None:
        svc, _ = _make_service()
        valid_profile = _profile(
            client_profile_id=_PROFILE_ID,
            platform_key="line",
            profile_key="a",
        )
        skipped_profile = _profile(
            client_profile_id=_SECONDARY_PROFILE_ID,
            platform_key="line",
            profile_key="b",
        )
        skipped_profile.id = None
        svc.list = AsyncMock(  # type: ignore[method-assign]
            return_value=[valid_profile, skipped_profile]
        )
        svc.build_runtime_config = AsyncMock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(line=SimpleNamespace(key="a"))
        )

        specs = await svc.list_active_runtime_specs(
            config={"mugen": {"platforms": ["line"]}},
            platform_key=" LINE ",
        )
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].client_profile_id, _PROFILE_ID)
        self.assertEqual(specs[0].platform_key, "line")
        self.assertEqual(specs[0].profile_key, "a")
        self.assertEqual(specs[0].snapshot["profile_key"], "a")
        self.assertEqual(
            svc.list.await_args.kwargs["filter_groups"][0].where,
            {"platform_key": "line", "is_active": True},
        )

        svc.get = AsyncMock(return_value=valid_profile)  # type: ignore[method-assign]
        self.assertEqual(
            await svc.resolve_active_by_id(client_profile_id=f" {_PROFILE_ID} "),
            valid_profile,
        )
        self.assertEqual(
            svc.get.await_args.args[0],
            {"id": _PROFILE_ID, "is_active": True},
        )

        self.assertIsNone(
            await svc.resolve_active_by_identifier(
                platform_key="line",
                identifier_type="path_token",
                identifier_value=" ",
            )
        )
        self.assertIsNone(
            await svc.resolve_active_by_identifier(
                platform_key="line",
                identifier_type="unsupported",
                identifier_value="token",
            )
        )

        svc.list = AsyncMock(  # type: ignore[method-assign]
            side_effect=[[valid_profile], [valid_profile, valid_profile]]
        )
        resolved = await svc.resolve_active_by_identifier(
            platform_key="line",
            identifier_type="path_token",
            identifier_value=" line-path ",
            filters={
                "provider": " official_account ",
                "unknown": "skip",
                "": "ignored",
                "provider_blank": " ",
            },
        )
        self.assertEqual(resolved, valid_profile)
        self.assertEqual(
            svc.list.await_args_list[0].kwargs["filter_groups"][0].where,
            {
                "platform_key": "line",
                "is_active": True,
                "path_token": "line-path",
                "provider": "official_account",
            },
        )
        self.assertIsNone(
            await svc.resolve_active_by_identifier(
                platform_key="line",
                identifier_type="path_token",
                identifier_value="line-path",
            )
        )

    async def test_create_update_and_delete_lifecycle_paths(self) -> None:
        svc, key_ref_service = _make_service()
        key_ref_service.get = AsyncMock(
            return_value=SimpleNamespace(id=_KEY_REF_ID)
        )
        svc._reload_runtime_profiles_for_platforms = (
            AsyncMock()  # type: ignore[method-assign]
        )

        created_profile = _profile()
        with patch.object(
            IRelationalService,
            "create",
            new=AsyncMock(return_value=created_profile),
        ) as base_create:
            created = await svc.create(
                {
                    "tenant_id": None,
                    "platform_key": " line ",
                    "profile_key": " support ",
                    "display_name": " Support ",
                    "settings": {},
                    "secret_refs": {"channel.secret": str(_KEY_REF_ID)},
                    "path_token": " line-path ",
                }
            )
        self.assertEqual(created, created_profile)
        self.assertEqual(
            base_create.await_args.args[0],
            {
                "tenant_id": GLOBAL_TENANT_ID,
                "platform_key": "line",
                "profile_key": "support",
                "display_name": "Support",
                "settings": {},
                "secret_refs": {"channel.secret": str(_KEY_REF_ID)},
                "path_token": "line-path",
                "recipient_user_id": None,
                "account_number": None,
                "phone_number_id": None,
                "provider": None,
            },
        )
        svc._reload_runtime_profiles_for_platforms.assert_awaited_with(
            "line"
        )  # type: ignore[union-attr]

        with self.assertRaises(HTTPException) as ctx:
            await svc.create(
                {
                    "tenant_id": None,
                    "platform_key": "telegram",
                    "profile_key": "bot",
                    "settings": {"webhook": {"path_token": "blocked"}},
                    "secret_refs": {},
                }
            )
        self.assertEqual(ctx.exception.code, 400)
        self.assertIn("Settings path 'webhook.path_token'", str(ctx.exception))

        current = _profile(
            platform_key="line",
            profile_key="support",
            settings={},
            secret_refs={"channel.secret": str(_KEY_REF_ID)},
            path_token="line-path",
        )
        updated_profile = _profile(
            platform_key="telegram",
            profile_key="support-updated",
            settings={},
            secret_refs={"bot.token": str(_KEY_REF_ID)},
            path_token="telegram-path",
        )

        svc.get = AsyncMock(  # type: ignore[method-assign]
            side_effect=[None, current, current]
        )
        with patch.object(
            IRelationalService,
            "update",
            new=AsyncMock(side_effect=[updated_profile, None]),
        ) as base_update:
            self.assertIsNone(
                await svc.update({"id": _PROFILE_ID}, {"profile_key": "x"})
            )
            updated = await svc.update(
                {"id": _PROFILE_ID},
                {
                    "platform_key": "telegram",
                    "profile_key": " support-updated ",
                    "settings": {},
                    "secret_refs": {"bot.token": str(_KEY_REF_ID)},
                    "path_token": " telegram-path ",
                    "is_active": False,
                },
            )
            self.assertEqual(updated, updated_profile)
            self.assertIsNone(
                await svc.update(
                    {"id": _PROFILE_ID},
                    {"profile_key": "support-updated"},
                )
            )
        self.assertEqual(
            base_update.await_args_list[0].args[1],
            {
                "tenant_id": _TENANT_ID,
                "platform_key": "telegram",
                "profile_key": "support-updated",
                "display_name": "Support",
                "settings": {},
                "secret_refs": {"bot.token": str(_KEY_REF_ID)},
                "is_active": False,
                "path_token": "telegram-path",
                "recipient_user_id": None,
                "account_number": None,
                "phone_number_id": None,
                "provider": None,
            },
        )

        svc.get = AsyncMock(return_value=current)  # type: ignore[method-assign]
        with self.assertRaises(HTTPException) as ctx:
            await svc.update(
                {"id": _PROFILE_ID},
                {
                    "platform_key": "matrix",
                    "secret_refs": {"bot.token": str(_KEY_REF_ID)},
                },
            )
        self.assertEqual(ctx.exception.code, 400)
        self.assertIn("SecretRefs path 'bot.token' is not allowed", str(ctx.exception))

        svc.get = AsyncMock(return_value=current)  # type: ignore[method-assign]
        with self.assertRaises(HTTPException) as ctx:
            await svc.update_with_row_version(
                {"id": _PROFILE_ID},
                expected_row_version=6,
                changes={
                    "platform_key": "matrix",
                    "secret_refs": {"bot.token": str(_KEY_REF_ID)},
                },
            )
        self.assertEqual(ctx.exception.code, 400)
        self.assertIn("SecretRefs path 'bot.token' is not allowed", str(ctx.exception))

        svc.get = AsyncMock(  # type: ignore[method-assign]
            side_effect=[current, current]
        )
        with patch.object(
            IRelationalService,
            "update_with_row_version",
            new=AsyncMock(side_effect=[updated_profile, None]),
        ) as base_update_with_row_version:
            svc.get = AsyncMock(return_value=None)  # type: ignore[method-assign]
            self.assertIsNone(
                await svc.update_with_row_version(
                    {"id": _PROFILE_ID},
                    expected_row_version=6,
                    changes={"profile_key": "support-updated"},
                )
            )
            svc.get = AsyncMock(  # type: ignore[method-assign]
                side_effect=[current, current]
            )
            updated_with_row_version = await svc.update_with_row_version(
                {"id": _PROFILE_ID},
                expected_row_version=7,
                changes={"profile_key": "support-updated"},
            )
            self.assertEqual(updated_with_row_version, updated_profile)
            self.assertIsNone(
                await svc.update_with_row_version(
                    {"id": _PROFILE_ID},
                    expected_row_version=8,
                    changes={"profile_key": "support-updated"},
                )
            )
        self.assertEqual(
            base_update_with_row_version.await_args_list[0].kwargs["changes"][
                "profile_key"
            ],
            "support-updated",
        )

        deleted_profile = _profile(platform_key="line")
        svc.get = AsyncMock(  # type: ignore[method-assign]
            side_effect=[current, current, current, current]
        )
        with patch.object(
            IRelationalService,
            "delete",
            new=AsyncMock(side_effect=[deleted_profile, None]),
        ), patch.object(
            IRelationalService,
            "delete_with_row_version",
            new=AsyncMock(side_effect=[deleted_profile, None]),
        ):
            svc.get = AsyncMock(return_value=None)  # type: ignore[method-assign]
            self.assertIsNone(await svc.delete({"id": _PROFILE_ID}))
            self.assertIsNone(
                await svc.delete_with_row_version(
                    {"id": _PROFILE_ID},
                    expected_row_version=2,
                )
            )
            svc.get = AsyncMock(  # type: ignore[method-assign]
                side_effect=[current, current, current, current]
            )
            deleted = await svc.delete({"id": _PROFILE_ID})
            self.assertEqual(deleted, deleted_profile)
            self.assertIsNone(await svc.delete({"id": _PROFILE_ID}))
            deleted_with_row_version = await svc.delete_with_row_version(
                {"id": _PROFILE_ID},
                expected_row_version=3,
            )
            self.assertEqual(deleted_with_row_version, deleted_profile)
            self.assertIsNone(
                await svc.delete_with_row_version(
                    {"id": _PROFILE_ID},
                    expected_row_version=4,
                )
            )

"""Tests for SystemFlagService ACP actions."""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import AsyncMock, patch

from mugen.core.plugin.acp.api.validation.generic import NoValidationSchema
from mugen.core.plugin.acp.service import system_flag as system_flag_mod


class _AbortCalled(Exception):
    def __init__(self, code: int, description: str | None = None) -> None:
        super().__init__(code, description)
        self.code = code
        self.description = description


def _abort_raiser(code: int, description: str | None = None, *_args, **_kwargs):
    raise _AbortCalled(code, description)


class TestMugenSystemFlagService(unittest.IsolatedAsyncioTestCase):
    """Covers the global ACP runtime-profile reload action."""

    async def test_entity_set_action_reload_platform_profiles_returns_helper_payload(
        self,
    ) -> None:
        service = system_flag_mod.SystemFlagService(table="system_flag", rsg=object())
        injector = object()
        payload = {"config_file": "mugen.toml", "platforms": {}}

        with (
            patch.object(
                system_flag_mod.di,
                "container",
                new=type("Container", (), {"build": staticmethod(lambda: injector)})(),
            ),
            patch.object(
                system_flag_mod,
                "reload_platform_runtime_profiles",
                new=AsyncMock(return_value=payload),
            ) as reload_profiles,
        ):
            result, status_code = await service.entity_set_action_reloadPlatformProfiles(
                auth_user_id=uuid.uuid4(),
                data=NoValidationSchema(),
            )

        reload_profiles.assert_awaited_once_with(injector=injector)
        self.assertEqual(status_code, 200)
        self.assertEqual(result, payload)

    async def test_entity_set_action_reload_platform_profiles_aborts_on_reload_error(
        self,
    ) -> None:
        service = system_flag_mod.SystemFlagService(table="system_flag", rsg=object())
        injector = object()

        with (
            patch.object(
                system_flag_mod.di,
                "container",
                new=type("Container", (), {"build": staticmethod(lambda: injector)})(),
            ),
            patch.object(
                system_flag_mod,
                "reload_platform_runtime_profiles",
                new=AsyncMock(
                    side_effect=system_flag_mod.PlatformRuntimeProfileReloadError(
                        "reload failed",
                        status_code=409,
                    )
                ),
            ),
            patch.object(system_flag_mod, "abort", side_effect=_abort_raiser),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await service.entity_set_action_reloadPlatformProfiles(
                    auth_user_id=uuid.uuid4(),
                    data=NoValidationSchema(),
                )

        self.assertEqual(ex.exception.code, 409)
        self.assertEqual(ex.exception.description, "reload failed")

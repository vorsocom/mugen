"""Unit tests for channel orchestration ChannelProfileService."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.plugin.channel_orchestration.service import (
    channel_profile as channel_profile_mod,
)
from mugen.core.plugin.channel_orchestration.service.channel_profile import (
    ChannelProfileService,
)
from mugen.core.utility.platform_runtime_profile import build_config_namespace


def _runtime_config() -> SimpleNamespace:
    return build_config_namespace(
        {
            "line": {
                "profiles": [
                    {
                        "key": "default",
                        "webhook": {"path_token": "line-path"},
                        "channel": {"secret": "line-secret"},
                    }
                ]
            },
            "matrix": {
                "profiles": [
                    {
                        "key": "default",
                        "client": {"user": "@bot:test"},
                    }
                ]
            },
        }
    )


class TestMuGenChannelProfileService(unittest.IsolatedAsyncioTestCase):
    """Covers runtime profile validation and CRUD payload normalization."""

    def test_private_runtime_profile_validation_helpers(self) -> None:
        config = _runtime_config()
        svc = ChannelProfileService(
            table="channel_profile",
            rsg=Mock(),
            config=config,
        )

        self.assertIsNone(svc._normalize_optional_text(None))  # pylint: disable=protected-access
        self.assertIsNone(svc._normalize_optional_text("   "))  # pylint: disable=protected-access
        self.assertEqual(
            svc._normalize_optional_text(" line "),  # pylint: disable=protected-access
            "line",
        )
        self.assertIs(svc._resolve_config(), config)  # pylint: disable=protected-access
        self.assertEqual(
            svc._validate_runtime_profile_key(  # pylint: disable=protected-access
                channel_key="web",
                runtime_profile_key=" secondary ",
            ),
            "secondary",
        )
        self.assertEqual(
            svc._validate_runtime_profile_key(  # pylint: disable=protected-access
                channel_key="line",
                runtime_profile_key=" default ",
            ),
            "default",
        )

        with self.assertRaisesRegex(RuntimeError, "required"):
            svc._validate_runtime_profile_key(  # pylint: disable=protected-access
                channel_key="line",
                runtime_profile_key=None,
            )

        with self.assertRaisesRegex(RuntimeError, "Unknown RuntimeProfileKey"):
            svc._validate_runtime_profile_key(  # pylint: disable=protected-access
                channel_key="line",
                runtime_profile_key="missing",
            )

        svc_without_config = ChannelProfileService(
            table="channel_profile",
            rsg=Mock(),
            config=None,
        )
        with patch.object(
            channel_profile_mod.di,
            "container",
            new=SimpleNamespace(config=config),
        ):
            self.assertIs(
                svc_without_config._resolve_config(),  # pylint: disable=protected-access
                config,
            )

        with patch.object(
            channel_profile_mod.di,
            "container",
            new=SimpleNamespace(),
        ):
            self.assertIsNone(
                svc_without_config._resolve_config()  # pylint: disable=protected-access
            )
            with self.assertRaisesRegex(RuntimeError, "requires runtime configuration"):
                svc_without_config._validate_runtime_profile_key(  # pylint: disable=protected-access
                    channel_key="line",
                    runtime_profile_key="default",
                )

    async def test_create_update_and_row_version_update_validate_runtime_profile_key(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        config = _runtime_config()
        rsg = Mock()
        rsg.insert_one = AsyncMock(
            return_value={
                "id": profile_id,
                "tenant_id": tenant_id,
                "channel_key": "line",
                "profile_key": "support",
                "runtime_profile_key": "default",
            }
        )
        rsg.update_one = AsyncMock(
            side_effect=[
                {
                    "id": profile_id,
                    "tenant_id": tenant_id,
                    "channel_key": "line",
                    "profile_key": "support",
                    "runtime_profile_key": "default",
                    "display_name": "Support",
                },
                {
                    "id": profile_id,
                    "tenant_id": tenant_id,
                    "channel_key": "line",
                    "profile_key": "support",
                    "runtime_profile_key": "default",
                    "display_name": "Support",
                    "row_version": 7,
                },
            ]
        )
        svc = ChannelProfileService(
            table="channel_profile",
            rsg=rsg,
            config=config,
        )

        created = await svc.create(
            {
                "tenant_id": tenant_id,
                "channel_key": "line",
                "profile_key": "support",
                "runtime_profile_key": " default ",
            }
        )
        self.assertEqual(created.runtime_profile_key, "default")
        self.assertEqual(
            rsg.insert_one.await_args.args[1]["runtime_profile_key"],
            "default",
        )

        current = SimpleNamespace(
            channel_key="line",
            runtime_profile_key="default",
        )
        svc.get = AsyncMock(side_effect=[current, None, current, None])

        updated = await svc.update(
            {"id": profile_id},
            {"display_name": "Support"},
        )
        self.assertEqual(updated.display_name, "Support")
        self.assertEqual(
            rsg.update_one.await_args_list[0].kwargs["changes"]["runtime_profile_key"],
            "default",
        )

        self.assertIsNone(
            await svc.update(
                {"id": profile_id},
                {"display_name": "Ignored"},
            )
        )

        updated_with_row_version = await svc.update_with_row_version(
            {"id": profile_id},
            expected_row_version=7,
            changes={"runtime_profile_key": " default "},
        )
        self.assertEqual(updated_with_row_version.runtime_profile_key, "default")
        self.assertEqual(
            rsg.update_one.await_args_list[1].kwargs["where"]["row_version"],
            7,
        )

        self.assertIsNone(
            await svc.update_with_row_version(
                {"id": profile_id},
                expected_row_version=8,
                changes={"runtime_profile_key": "default"},
            )
        )

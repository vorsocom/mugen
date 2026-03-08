"""Unit tests for channel orchestration ChannelProfileService."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, Mock

from mugen.core.plugin.channel_orchestration.service.channel_profile import (
    ChannelProfileService,
)


class TestMuGenChannelProfileService(unittest.IsolatedAsyncioTestCase):
    """Covers client profile validation and CRUD payload normalization."""

    async def test_private_client_profile_validation_helpers(self) -> None:
        tenant_id = uuid.uuid4()
        client_profile_id = uuid.uuid4()
        svc = ChannelProfileService(
            table="channel_profile",
            rsg=Mock(),
        )

        self.assertIsNone(svc._normalize_optional_text(None))  # pylint: disable=protected-access
        self.assertIsNone(svc._normalize_optional_text("   "))  # pylint: disable=protected-access
        self.assertEqual(
            svc._normalize_optional_text(" line "),  # pylint: disable=protected-access
            "line",
        )
        self.assertIsNone(svc._normalize_optional_uuid("bad"))  # pylint: disable=protected-access
        self.assertEqual(
            svc._normalize_optional_uuid(f" {client_profile_id} "),  # pylint: disable=protected-access
            client_profile_id,
        )

        self.assertIsNone(
            await svc._validate_client_profile_id(  # pylint: disable=protected-access
                channel_key="web",
                tenant_id=tenant_id,
                client_profile_id=None,
            )
        )

        with self.assertRaisesRegex(RuntimeError, "ClientProfileId is required"):
            await svc._validate_client_profile_id(  # pylint: disable=protected-access
                channel_key="line",
                tenant_id=tenant_id,
                client_profile_id=None,
            )

        with self.assertRaisesRegex(RuntimeError, "TenantId is required"):
            await svc._validate_client_profile_id(  # pylint: disable=protected-access
                channel_key="line",
                tenant_id=None,
                client_profile_id=client_profile_id,
            )

        svc._messaging_client_profile_service.get = AsyncMock(return_value=None)  # type: ignore[attr-defined]
        with self.assertRaisesRegex(RuntimeError, "Unknown ClientProfileId"):
            await svc._validate_client_profile_id(  # pylint: disable=protected-access
                channel_key="line",
                tenant_id=tenant_id,
                client_profile_id=client_profile_id,
            )

        svc._messaging_client_profile_service.get = AsyncMock(  # type: ignore[attr-defined]
            return_value=SimpleNamespace(platform_key="telegram")
        )
        with self.assertRaisesRegex(RuntimeError, "platform does not match"):
            await svc._validate_client_profile_id(  # pylint: disable=protected-access
                channel_key="line",
                tenant_id=tenant_id,
                client_profile_id=client_profile_id,
            )

        svc._messaging_client_profile_service.get = AsyncMock(  # type: ignore[attr-defined]
            return_value=SimpleNamespace(platform_key="line")
        )
        self.assertEqual(
            await svc._validate_client_profile_id(  # pylint: disable=protected-access
                channel_key="line",
                tenant_id=tenant_id,
                client_profile_id=f" {client_profile_id} ",
            ),
            client_profile_id,
        )

    async def test_create_update_and_row_version_update_validate_client_profile_id(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        client_profile_id = uuid.uuid4()
        rsg = Mock()
        rsg.insert_one = AsyncMock(
            return_value={
                "id": profile_id,
                "tenant_id": tenant_id,
                "channel_key": "line",
                "profile_key": "support",
                "client_profile_id": client_profile_id,
            }
        )
        rsg.update_one = AsyncMock(
            side_effect=[
                {
                    "id": profile_id,
                    "tenant_id": tenant_id,
                    "channel_key": "line",
                    "profile_key": "support",
                    "client_profile_id": client_profile_id,
                    "display_name": "Support",
                },
                {
                    "id": profile_id,
                    "tenant_id": tenant_id,
                    "channel_key": "line",
                    "profile_key": "support",
                    "client_profile_id": client_profile_id,
                    "display_name": "Support",
                    "row_version": 7,
                },
            ]
        )
        svc = ChannelProfileService(
            table="channel_profile",
            rsg=rsg,
        )
        svc._messaging_client_profile_service.get = AsyncMock(  # type: ignore[attr-defined]
            return_value=SimpleNamespace(platform_key="line")
        )

        created = await svc.create(
            {
                "tenant_id": tenant_id,
                "channel_key": "line",
                "profile_key": "support",
                "client_profile_id": f" {client_profile_id} ",
            }
        )
        self.assertEqual(created.client_profile_id, client_profile_id)
        self.assertEqual(
            rsg.insert_one.await_args.args[1]["client_profile_id"],
            client_profile_id,
        )

        current = SimpleNamespace(
            channel_key="line",
            tenant_id=tenant_id,
            client_profile_id=client_profile_id,
        )
        svc.get = AsyncMock(side_effect=[current, None, current, None])

        updated = await svc.update(
            {"id": profile_id},
            {"display_name": "Support"},
        )
        self.assertEqual(updated.display_name, "Support")
        self.assertEqual(
            rsg.update_one.await_args_list[0].kwargs["changes"]["client_profile_id"],
            client_profile_id,
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
            changes={"client_profile_id": f" {client_profile_id} "},
        )
        self.assertEqual(updated_with_row_version.client_profile_id, client_profile_id)
        self.assertEqual(
            rsg.update_one.await_args_list[1].kwargs["where"]["row_version"],
            7,
        )

        self.assertIsNone(
            await svc.update_with_row_version(
                {"id": profile_id},
                expected_row_version=8,
                changes={"client_profile_id": client_profile_id},
            )
        )

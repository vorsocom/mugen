"""Unit tests for channel_orchestration BlocklistEntryService."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import SQLAlchemyError

from mugen.core.plugin.channel_orchestration.api.validation import (
    BlockSenderActionValidation,
    UnblockSenderActionValidation,
)
from mugen.core.plugin.channel_orchestration.service import (
    blocklist_entry as blocklist_mod,
)
from mugen.core.plugin.channel_orchestration.service.blocklist_entry import (
    BlocklistEntryService,
)


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None, **_kwargs):
    raise _AbortCalled(code, message)


class TestMugenChannelOrchestrationBlocklistService(unittest.IsolatedAsyncioTestCase):
    """Covers helper logic and action branch paths for sender block/unblock."""

    async def test_helpers_and_find_active_entry(self) -> None:
        svc = BlocklistEntryService(table="blocklist", rsg=object())
        now = datetime(2026, 2, 14, tzinfo=timezone.utc)
        tenant_id = uuid.uuid4()
        profile_id = uuid.uuid4()

        self.assertIsNone(svc._normalize_optional_text(None))  # pylint: disable=protected-access
        self.assertIsNone(svc._normalize_optional_text("   "))  # pylint: disable=protected-access
        self.assertEqual(svc._normalize_optional_text("  x "), "x")  # pylint: disable=protected-access
        self.assertTrue(svc._same_channel_profile(profile_id, profile_id))  # pylint: disable=protected-access
        self.assertFalse(svc._same_channel_profile(profile_id, uuid.uuid4()))  # pylint: disable=protected-access

        rows = [
            SimpleNamespace(
                id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                is_active=True,
                sender_key="Sender",
                channel_profile_id=profile_id,
                expires_at=None,
            ),
            SimpleNamespace(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                is_active=False,
                sender_key="Sender",
                channel_profile_id=profile_id,
                expires_at=None,
            ),
            SimpleNamespace(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                is_active=True,
                sender_key="Different",
                channel_profile_id=profile_id,
                expires_at=None,
            ),
            SimpleNamespace(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                is_active=True,
                sender_key="Sender",
                channel_profile_id=uuid.uuid4(),
                expires_at=None,
            ),
            SimpleNamespace(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                is_active=True,
                sender_key="Sender",
                channel_profile_id=profile_id,
                expires_at=now - timedelta(minutes=1),
            ),
            SimpleNamespace(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                is_active=True,
                sender_key="sender",
                channel_profile_id=profile_id,
                expires_at=now + timedelta(minutes=5),
            ),
        ]

        svc.list = AsyncMock(return_value=rows)
        svc._now_utc = staticmethod(lambda: now)  # pylint: disable=protected-access
        found = await svc._find_active_entry(  # pylint: disable=protected-access
            tenant_id=tenant_id,
            sender_key="SENDER",
            channel_profile_id=profile_id,
        )
        self.assertIs(found, rows[-1])

        svc.list = AsyncMock(return_value=rows[:-1])
        missing = await svc._find_active_entry(  # pylint: disable=protected-access
            tenant_id=tenant_id,
            sender_key="SENDER",
            channel_profile_id=profile_id,
        )
        self.assertIsNone(missing)

    async def test_action_block_sender_paths(self) -> None:
        svc = BlocklistEntryService(table="blocklist", rsg=object())
        tenant_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        data = BlockSenderActionValidation(sender_key="sender", reason="reason")
        common = {
            "tenant_id": tenant_id,
            "where": {},
            "auth_user_id": auth_user_id,
            "data": data,
        }

        with patch.object(blocklist_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_block_sender(
                    tenant_id=tenant_id,
                    where={},
                    auth_user_id=auth_user_id,
                    data=SimpleNamespace(
                        sender_key=" ",
                        channel_profile_id=None,
                        reason=None,
                        expires_at=None,
                        attributes=None,
                    ),
                )
            self.assertEqual(ex.exception.code, 400)

        svc._find_active_entry = AsyncMock(return_value=None)  # pylint: disable=protected-access
        svc.create = AsyncMock(side_effect=SQLAlchemyError("db"))
        with patch.object(blocklist_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_block_sender(**common)
            self.assertEqual(ex.exception.code, 500)

        svc._find_active_entry = AsyncMock(return_value=None)  # pylint: disable=protected-access
        svc.create = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
        svc._event_service.create = AsyncMock(side_effect=SQLAlchemyError("db"))  # pylint: disable=protected-access
        with patch.object(blocklist_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_block_sender(**common)
            self.assertEqual(ex.exception.code, 500)

        svc._find_active_entry = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(id=uuid.uuid4())
        )
        svc.update = AsyncMock(side_effect=SQLAlchemyError("db"))
        with patch.object(blocklist_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_block_sender(**common)
            self.assertEqual(ex.exception.code, 500)

        svc._find_active_entry = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(id=uuid.uuid4())
        )
        svc.update = AsyncMock(return_value=None)
        with patch.object(blocklist_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_block_sender(**common)
            self.assertEqual(ex.exception.code, 404)

        svc._find_active_entry = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(id=uuid.uuid4())
        )
        updated = SimpleNamespace(id=uuid.uuid4())
        svc.update = AsyncMock(return_value=updated)
        svc._event_service.create = AsyncMock(side_effect=SQLAlchemyError("db"))  # pylint: disable=protected-access
        with patch.object(blocklist_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_block_sender(**common)
            self.assertEqual(ex.exception.code, 500)

        svc._find_active_entry = AsyncMock(return_value=None)  # pylint: disable=protected-access
        created = SimpleNamespace(id=uuid.uuid4())
        svc.create = AsyncMock(return_value=created)
        svc._event_service.create = AsyncMock(return_value=SimpleNamespace())  # pylint: disable=protected-access
        created_result = await svc.action_block_sender(**common)
        self.assertEqual(created_result, ({"BlocklistEntryId": str(created.id), "Status": "blocked"}, 200))

        svc._find_active_entry = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(id=uuid.uuid4())
        )
        updated = SimpleNamespace(id=uuid.uuid4())
        svc.update = AsyncMock(return_value=updated)
        svc._event_service.create = AsyncMock(return_value=SimpleNamespace())  # pylint: disable=protected-access
        updated_result = await svc.action_block_sender(**common)
        self.assertEqual(updated_result, ({"BlocklistEntryId": str(updated.id), "Status": "blocked"}, 200))

    async def test_action_unblock_sender_paths(self) -> None:
        svc = BlocklistEntryService(table="blocklist", rsg=object())
        tenant_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        data = UnblockSenderActionValidation(sender_key="sender", reason="reason")
        common = {
            "tenant_id": tenant_id,
            "where": {},
            "auth_user_id": auth_user_id,
            "data": data,
        }

        with patch.object(blocklist_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_unblock_sender(
                    tenant_id=tenant_id,
                    where={},
                    auth_user_id=auth_user_id,
                    data=SimpleNamespace(
                        sender_key=" ",
                        channel_profile_id=None,
                        reason=None,
                    ),
                )
            self.assertEqual(ex.exception.code, 400)

        svc._find_active_entry = AsyncMock(return_value=None)  # pylint: disable=protected-access
        with patch.object(blocklist_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_unblock_sender(**common)
            self.assertEqual(ex.exception.code, 404)

        svc._find_active_entry = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(id=uuid.uuid4())
        )
        svc.update = AsyncMock(side_effect=SQLAlchemyError("db"))
        with patch.object(blocklist_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_unblock_sender(**common)
            self.assertEqual(ex.exception.code, 500)

        svc._find_active_entry = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(id=uuid.uuid4())
        )
        svc.update = AsyncMock(return_value=None)
        with patch.object(blocklist_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_unblock_sender(**common)
            self.assertEqual(ex.exception.code, 404)

        svc._find_active_entry = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(id=uuid.uuid4())
        )
        updated = SimpleNamespace(id=uuid.uuid4())
        svc.update = AsyncMock(return_value=updated)
        svc._event_service.create = AsyncMock(side_effect=SQLAlchemyError("db"))  # pylint: disable=protected-access
        with patch.object(blocklist_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_unblock_sender(**common)
            self.assertEqual(ex.exception.code, 500)

        svc._find_active_entry = AsyncMock(  # pylint: disable=protected-access
            return_value=SimpleNamespace(id=uuid.uuid4())
        )
        updated = SimpleNamespace(id=uuid.uuid4())
        svc.update = AsyncMock(return_value=updated)
        svc._event_service.create = AsyncMock(return_value=SimpleNamespace())  # pylint: disable=protected-access
        result = await svc.action_unblock_sender(**common)
        self.assertEqual(result, ({"BlocklistEntryId": str(updated.id), "Status": "unblocked"}, 200))

"""Regression tests for current conversation authorization on media downloads."""

import asyncio
from datetime import datetime, timedelta, timezone
from inspect import unwrap
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from werkzeug.exceptions import NotFound

from mugen.core.client.web import DefaultWebClient
from mugen.core.constants import GLOBAL_TENANT_ID
from mugen.core.plugin.web.api import chat
from mugen.core.plugin.web.api.decorator import web_access_required


class TestWebMediaAuthorization(unittest.IsolatedAsyncioTestCase):
    """Exercise the real route and resolver before media materialization."""

    def setUp(self) -> None:
        self.owner = str(uuid.uuid4())
        self.tenant_id = uuid.uuid4()
        self.token_row = {
            "owner_user_id": self.owner,
            "conversation_id": "tenant-conversation",
            "file_path": "object:" + uuid.uuid4().hex,
            "filename": "report.txt",
            "mime_type": "text/plain",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        }
        self.store = SimpleNamespace(
            get_media_token=AsyncMock(return_value=self.token_row),
            get_conversation_tenant_id=AsyncMock(return_value=self.tenant_id),
            delete_media_token=AsyncMock(),
        )
        self.auth = SimpleNamespace(
            has_permission=AsyncMock(return_value=True),
            has_permission_for_any_tenant=AsyncMock(return_value=True),
        )
        self.materialize = AsyncMock(return_value="/synthetic/report.txt")
        self.client = DefaultWebClient.__new__(DefaultWebClient)
        self.client._storage_lock = asyncio.Lock()
        self.client._web_runtime_store = self.store
        self.client._media_storage_gateway = SimpleNamespace(
            materialize=self.materialize,
        )
        self.endpoint = web_access_required(
            unwrap(chat.web_media_download),
            auth_provider=lambda: self.auth,
            logger_provider=lambda: Mock(),
        )

    async def _download(self):
        return await self.endpoint(
            auth_user=self.owner,
            token="owner-token",
            web_client_provider=lambda: self.client,
            auth_provider=lambda: self.auth,
        )

    async def test_revocation_blocks_media_despite_other_tenant_access(self) -> None:
        with (
            patch.object(chat.os.path, "exists", return_value=True),
            patch.object(chat, "send_file", new=AsyncMock(return_value="sent")),
        ):
            self.assertEqual(await self._download(), "sent")
            self.auth.has_permission.return_value = False
            with self.assertRaises(NotFound):
                await self._download()

        self.assertEqual(self.auth.has_permission_for_any_tenant.await_count, 2)
        self.assertEqual(self.auth.has_permission.await_count, 2)
        self.auth.has_permission.assert_awaited_with(
            user_id=uuid.UUID(self.owner),
            tenant_id=self.tenant_id,
            permission_object=chat.WEB_PLATFORM_ACCESS_PERMISSION,
            permission_type=chat.WEB_PLATFORM_ACCESS_PERMISSION,
            allow_global_admin=True,
        )
        self.assertEqual(self.store.get_conversation_tenant_id.await_count, 2)
        self.store.get_conversation_tenant_id.assert_awaited_with(
            auth_user=self.owner,
            conversation_id="tenant-conversation",
        )
        self.materialize.assert_awaited_once_with(self.token_row["file_path"])

    async def test_missing_or_no_longer_owned_conversation_blocks_media(self) -> None:
        self.store.get_conversation_tenant_id.return_value = None
        with self.assertRaises(NotFound):
            await self._download()
        self.auth.has_permission.assert_not_awaited()
        self.materialize.assert_not_awaited()

    async def test_global_conversation_uses_current_global_web_access(self) -> None:
        self.store.get_conversation_tenant_id.return_value = GLOBAL_TENANT_ID
        with (
            patch.object(chat.os.path, "exists", return_value=True),
            patch.object(chat, "send_file", new=AsyncMock(return_value="sent")),
        ):
            self.assertEqual(await self._download(), "sent")
            self.auth.has_permission_for_any_tenant.side_effect = [True, False]
            with self.assertRaises(NotFound):
                await self._download()

        self.auth.has_permission.assert_not_awaited()
        self.materialize.assert_awaited_once()

    async def test_invalid_token_conversation_never_reaches_authorization(self) -> None:
        for conversation_id in (None, 1, "", "   "):
            with self.subTest(conversation_id=conversation_id):
                self.token_row["conversation_id"] = conversation_id
                with self.assertRaises(NotFound):
                    await self._download()
        self.store.get_conversation_tenant_id.assert_not_awaited()
        self.materialize.assert_not_awaited()

    async def test_authorization_failure_never_materializes_media(self) -> None:
        self.auth.has_permission.side_effect = RuntimeError("authorization unavailable")
        with self.assertRaisesRegex(RuntimeError, "authorization unavailable"):
            await self._download()
        self.materialize.assert_not_awaited()

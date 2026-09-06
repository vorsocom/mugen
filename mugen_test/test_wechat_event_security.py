"""Reject unsigned event bodies and expired WeChat delivery signatures."""

from inspect import unwrap
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from quart import Quart

from mugen.core.plugin.wechat.api import webhook
from mugen_test.test_mugen_wechat_api_webhook import (
    _ClientProfileServiceStub,
    _make_config,
)
from mugen_test.wechat_fixtures import encrypted_event


class TestWeChatEventSecurity(unittest.IsolatedAsyncioTestCase):
    """Exercise encrypted event authentication before any IPC side effect."""

    def setUp(self) -> None:
        self.config = _make_config(aes_enabled=True)
        self.ipc = SimpleNamespace(
            handle_ipc_request=AsyncMock(return_value=SimpleNamespace(errors=[]))
        )
        self.app = Quart(__name__)
        self.enterContext(patch.object(webhook, "time", return_value=1000.0))

        @self.app.post("/webhook")
        async def event():
            return await unwrap(webhook.wechat_official_account_event)(
                path_token="path-token-1",
                config_provider=lambda: self.config,
                ipc_provider=lambda: self.ipc,
                logger_provider=Mock,
                client_profile_service_provider=_ClientProfileServiceStub,
            )

    async def test_encrypted_body_is_bound_to_signature(self) -> None:
        original = "<xml><MsgId>one</MsgId><Content>original</Content></xml>"
        changed = "<xml><MsgId>two</MsgId><Content>changed</Content></xml>"
        body, query = encrypted_event(
            original,
            token=self.config.wechat.webhook.signature_token,
            timestamp="1000",
        )
        response = await self.app.test_client().post(
            "/webhook", query_string=query, data=body
        )
        self.assertEqual(response.status_code, 200)
        self.ipc.handle_ipc_request.assert_awaited_once()
        sent = self.ipc.handle_ipc_request.await_args.args[0]
        self.assertEqual(sent.data["payload"]["Content"], "original")

        changed_body, _ = encrypted_event(
            changed,
            token=self.config.wechat.webhook.signature_token,
            timestamp="1000",
        )
        response = await self.app.test_client().post(
            "/webhook", query_string=query, data=changed_body
        )
        self.assertEqual(response.status_code, 401)
        self.ipc.handle_ipc_request.assert_awaited_once()

    async def test_plaintext_signature_cannot_authorize_any_event_body(self) -> None:
        signature = webhook._compute_signature(
            token=self.config.wechat.webhook.signature_token,
            timestamp="1000",
            nonce="2",
            encrypted=None,
        )
        query = {"signature": signature, "timestamp": "1000", "nonce": "2"}
        for aes_enabled in (False, True):
            self.config.wechat.webhook.aes_enabled = aes_enabled
            for msg_id in ("original", "substituted"):
                with self.subTest(aes_enabled=aes_enabled, msg_id=msg_id):
                    response = await self.app.test_client().post(
                        "/webhook",
                        query_string=query,
                        data=f"<xml><MsgId>{msg_id}</MsgId></xml>",
                    )
                    self.assertEqual(response.status_code, 400)
        self.ipc.handle_ipc_request.assert_not_awaited()

    async def test_timestamp_window_rejects_replay_and_invalid_values(self) -> None:
        for timestamp, status in (
            ("699", 401),
            ("1301", 401),
            ("0", 401),
            ("-1", 401),
            ("invalid", 400),
            ("9" * 400, 401),
        ):
            with self.subTest(timestamp=timestamp):
                body, query = encrypted_event(
                    "<xml><MsgId>one</MsgId></xml>",
                    token=self.config.wechat.webhook.signature_token,
                    timestamp=timestamp,
                )
                response = await self.app.test_client().post(
                    "/webhook", query_string=query, data=body
                )
                self.assertEqual(response.status_code, status)
        self.ipc.handle_ipc_request.assert_not_awaited()

    async def test_timestamp_window_accepts_both_boundaries(self) -> None:
        for timestamp in ("700", "1300"):
            body, query = encrypted_event(
                "<xml><MsgId>one</MsgId></xml>",
                token=self.config.wechat.webhook.signature_token,
                timestamp=timestamp,
            )
            response = await self.app.test_client().post(
                "/webhook", query_string=query, data=body
            )
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.ipc.handle_ipc_request.await_count, 2)

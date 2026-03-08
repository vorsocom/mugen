"""Reliability E2E tests for WeChat webhook + IPC processing."""

from inspect import unwrap
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from sqlalchemy.exc import IntegrityError

from mugen.core.contract.service.ingress_routing import (
    IngressRouteResolution,
    IngressRouteResult,
)
from mugen.core.plugin.wechat.api import webhook
from mugen.core.plugin.wechat.ipc_ext import WeChatIPCExtension
from mugen.core.service.ipc import DefaultIPCService

_CLIENT_PROFILE_ID = uuid.UUID("00000000-0000-0000-0000-000000000203")


class _MemoryRelational:
    def __init__(self) -> None:
        self.event_dedup: dict[tuple[str, str], dict] = {}
        self.dead_letters: list[dict] = []

    async def insert_one(self, table: str, record: dict):
        if table == "wechat_event_dedup":
            key = (record["event_type"], record["dedupe_key"])
            if key in self.event_dedup:
                raise IntegrityError("insert", {}, Exception("duplicate"))
            self.event_dedup[key] = dict(record)
            return dict(record)
        if table == "wechat_event_dead_letter":
            self.dead_letters.append(dict(record))
            return dict(record)
        raise ValueError(f"Unsupported table: {table}")

    async def update_one(self, table: str, where: dict, changes: dict):
        if table != "wechat_event_dedup":
            raise ValueError(f"Unsupported table: {table}")
        key = (where.get("event_type"), where.get("dedupe_key"))
        existing = self.event_dedup.get(key)
        if existing is None:
            return None
        existing.update(changes)
        return dict(existing)


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        mugen=SimpleNamespace(
            platforms=["wechat"],
            runtime=SimpleNamespace(
                profile="platform_full",
                provider_readiness_timeout_seconds=15.0,
                provider_shutdown_timeout_seconds=10.0,
                shutdown_timeout_seconds=60.0,
                phase_b=SimpleNamespace(startup_timeout_seconds=30.0),
            ),
        ),
        wechat=SimpleNamespace(
            webhook=SimpleNamespace(
                path_token="path-token",
                signature_token="signature-token",
                aes_enabled=False,
                aes_key="0123456789abcdef0123456789abcdef0123456789A",
                dedupe_ttl_seconds=86400,
            ),
            typing=SimpleNamespace(enabled=True),
        ),
    )


def _make_client() -> SimpleNamespace:
    return SimpleNamespace(
        send_audio_message=AsyncMock(return_value={"ok": True, "data": {}}),
        send_file_message=AsyncMock(return_value={"ok": True, "data": {}}),
        send_image_message=AsyncMock(return_value={"ok": True, "data": {}}),
        send_text_message=AsyncMock(return_value={"ok": True, "data": {}}),
        send_video_message=AsyncMock(return_value={"ok": True, "data": {}}),
        send_raw_message=AsyncMock(return_value={"ok": True, "data": {}}),
        emit_processing_signal=AsyncMock(return_value=True),
        download_media=AsyncMock(
            return_value={
                "path": "/tmp/file.bin",
                "mime_type": "application/octet-stream",
                "size": 2,
            }
        ),
        upload_media=AsyncMock(return_value={"ok": True, "data": {"media_id": "m-1"}}),
    )


class _IngressRoutingStub:
    async def resolve(self, request) -> IngressRouteResolution:
        identifier_value = request.identifier_value
        if not isinstance(identifier_value, str) or identifier_value.strip() == "":
            identifier_value = "path-token"
        return IngressRouteResolution(
            ok=True,
            result=IngressRouteResult(
                tenant_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
                tenant_slug="tenant-a",
                platform="wechat",
                channel_key="wechat",
                client_profile_id=_CLIENT_PROFILE_ID,
                client_profile_key="wechat-a",
                identifier_claims={
                    "identifier_type": "path_token",
                    "identifier_value": str(identifier_value),
                },
            ),
        )


class _ClientProfileServiceStub:
    async def resolve_active_by_identifier(self, **_kwargs):
        return SimpleNamespace(
            id=_CLIENT_PROFILE_ID,
            tenant_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            platform_key="wechat",
            profile_key="wechat-a",
            path_token="path-token",
            provider="official_account",
        )

    async def build_runtime_config(self, *, config, client_profile):  # noqa: ARG002
        return config


def _new_extension(
    *,
    logger: Mock,
    relational_gateway: _MemoryRelational,
    messaging_service: SimpleNamespace,
    user_service: SimpleNamespace,
    client: SimpleNamespace,
) -> WeChatIPCExtension:
    return WeChatIPCExtension(
        config=_make_config(),
        logging_gateway=logger,
        relational_storage_gateway=relational_gateway,
        messaging_service=messaging_service,
        user_service=user_service,
        wechat_client=client,
        ingress_routing_service=_IngressRoutingStub(),
    )


def _new_ipc_service(*, logger: Mock, ipc_ext: WeChatIPCExtension) -> DefaultIPCService:
    ipc_service = DefaultIPCService(
        config=SimpleNamespace(),
        logging_gateway=logger,
    )
    ipc_service.bind_ipc_extension(ipc_ext)
    return ipc_service


def _signature_for_plain(token: str, *, timestamp: str = "1", nonce: str = "2") -> str:
    return webhook._compute_signature(  # pylint: disable=protected-access
        token=token,
        timestamp=timestamp,
        nonce=nonce,
        encrypted=None,
    )


def _text_event_xml(*, msg_id: str = "1001", text: str = "hello") -> str:
    return (
        "<xml>"
        "<FromUserName>user-1</FromUserName>"
        "<MsgType>text</MsgType>"
        f"<Content>{text}</Content>"
        f"<MsgId>{msg_id}</MsgId>"
        "</xml>"
    )


def _voice_event_xml(*, msg_id: str = "1002", media_id: str = "media-1") -> str:
    return (
        "<xml>"
        "<FromUserName>user-1</FromUserName>"
        "<MsgType>voice</MsgType>"
        f"<MediaId>{media_id}</MediaId>"
        f"<MsgId>{msg_id}</MsgId>"
        "</xml>"
    )


class TestMugenWeChatReliabilityE2E(unittest.IsolatedAsyncioTestCase):
    """Exercises dedupe, media, and dead-letter reliability behavior."""

    async def test_duplicate_delivery_is_processed_once(self) -> None:
        logger = Mock()
        relational_gateway = _MemoryRelational()
        messaging_service = SimpleNamespace(
            handle_audio_message=AsyncMock(return_value=[]),
            handle_file_message=AsyncMock(return_value=[]),
            handle_image_message=AsyncMock(return_value=[]),
            handle_text_message=AsyncMock(return_value=[]),
            handle_video_message=AsyncMock(return_value=[]),
            mh_extensions=[],
        )
        user_service = SimpleNamespace(
            get_known_users_list=AsyncMock(return_value={"user-1": "Known User"}),
            add_known_user=AsyncMock(),
        )
        client = _make_client()

        ipc_ext = _new_extension(
            logger=logger,
            relational_gateway=relational_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
            client=client,
        )
        ipc_service = _new_ipc_service(logger=logger, ipc_ext=ipc_ext)
        endpoint = unwrap(webhook.wechat_official_account_event)
        cfg = _make_config()
        payload_xml = _text_event_xml(msg_id="7001", text="hello")
        signature = _signature_for_plain(cfg.wechat.webhook.signature_token)

        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(
                args={"timestamp": "1", "nonce": "2", "signature": signature},
                get_data=AsyncMock(return_value=payload_xml.encode("utf-8")),
            ),
        ):
            first = await endpoint(
                path_token="path-token",
                config_provider=lambda: cfg,
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
                client_profile_service_provider=lambda: _ClientProfileServiceStub(),
            )

        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(
                args={"timestamp": "1", "nonce": "2", "signature": signature},
                get_data=AsyncMock(return_value=payload_xml.encode("utf-8")),
            ),
        ):
            second = await endpoint(
                path_token="path-token",
                config_provider=lambda: cfg,
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
                client_profile_service_provider=lambda: _ClientProfileServiceStub(),
            )

        self.assertEqual(first, "success")
        self.assertEqual(second, "success")
        kwargs = messaging_service.handle_text_message.await_args.kwargs
        self.assertEqual(kwargs["room_id"], "user-1")
        self.assertEqual(kwargs["sender"], "user-1")
        self.assertEqual(kwargs["message"], "hello")
        ingress_route = kwargs["message_context"][-1]["content"]
        self.assertEqual(ingress_route["platform"], "wechat")
        self.assertEqual(ingress_route["client_profile_id"], str(_CLIENT_PROFILE_ID))
        self.assertEqual(ingress_route["client_profile_key"], "wechat-a")
        logger.debug.assert_any_call("Skip duplicate WeChat event.")

    async def test_voice_event_routes_download_and_audio_handler(self) -> None:
        logger = Mock()
        relational_gateway = _MemoryRelational()
        messaging_service = SimpleNamespace(
            handle_audio_message=AsyncMock(return_value=[]),
            handle_file_message=AsyncMock(return_value=[]),
            handle_image_message=AsyncMock(return_value=[]),
            handle_text_message=AsyncMock(return_value=[]),
            handle_video_message=AsyncMock(return_value=[]),
            mh_extensions=[],
        )
        user_service = SimpleNamespace(
            get_known_users_list=AsyncMock(return_value={"user-1": "Known User"}),
            add_known_user=AsyncMock(),
        )
        client = _make_client()

        ipc_ext = _new_extension(
            logger=logger,
            relational_gateway=relational_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
            client=client,
        )
        ipc_service = _new_ipc_service(logger=logger, ipc_ext=ipc_ext)
        endpoint = unwrap(webhook.wechat_official_account_event)
        cfg = _make_config()
        payload_xml = _voice_event_xml(msg_id="7002", media_id="media-123")
        signature = _signature_for_plain(cfg.wechat.webhook.signature_token)

        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(
                args={"timestamp": "1", "nonce": "2", "signature": signature},
                get_data=AsyncMock(return_value=payload_xml.encode("utf-8")),
            ),
        ):
            response = await endpoint(
                path_token="path-token",
                config_provider=lambda: cfg,
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
                client_profile_service_provider=lambda: _ClientProfileServiceStub(),
            )

        self.assertEqual(response, "success")
        client.download_media.assert_awaited_once_with(media_id="media-123")
        messaging_service.handle_audio_message.assert_awaited_once()
        routed = messaging_service.handle_audio_message.await_args.kwargs["message"]
        self.assertEqual(routed["file"], "/tmp/file.bin")

    async def test_processing_failure_is_persisted_to_dead_letter(self) -> None:
        logger = Mock()
        relational_gateway = _MemoryRelational()
        messaging_service = SimpleNamespace(
            handle_audio_message=AsyncMock(return_value=[]),
            handle_file_message=AsyncMock(return_value=[]),
            handle_image_message=AsyncMock(return_value=[]),
            handle_text_message=AsyncMock(side_effect=RuntimeError("boom")),
            handle_video_message=AsyncMock(return_value=[]),
            mh_extensions=[],
        )
        user_service = SimpleNamespace(
            get_known_users_list=AsyncMock(return_value={"user-1": "Known User"}),
            add_known_user=AsyncMock(),
        )
        client = _make_client()

        ipc_ext = _new_extension(
            logger=logger,
            relational_gateway=relational_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
            client=client,
        )
        ipc_service = _new_ipc_service(logger=logger, ipc_ext=ipc_ext)
        endpoint = unwrap(webhook.wechat_official_account_event)
        cfg = _make_config()
        payload_xml = _text_event_xml(msg_id="7003", text="boom")
        signature = _signature_for_plain(cfg.wechat.webhook.signature_token)

        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(
                args={"timestamp": "1", "nonce": "2", "signature": signature},
                get_data=AsyncMock(return_value=payload_xml.encode("utf-8")),
            ),
        ):
            response = await endpoint(
                path_token="path-token",
                config_provider=lambda: cfg,
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
                client_profile_service_provider=lambda: _ClientProfileServiceStub(),
            )

        self.assertEqual(response, "success")
        self.assertEqual(len(relational_gateway.dead_letters), 1)
        self.assertEqual(
            relational_gateway.dead_letters[0]["reason_code"],
            "processing_exception",
        )

    async def test_malformed_wecom_payload_is_rejected_pre_ipc(self) -> None:
        endpoint = unwrap(webhook.wechat_wecom_event)
        cfg = _make_config()
        logger = Mock()
        ipc_service = SimpleNamespace(handle_ipc_request=AsyncMock())
        signature = _signature_for_plain(cfg.wechat.webhook.signature_token)

        with (
            patch.object(webhook, "abort", side_effect=lambda code: (_ for _ in ()).throw(RuntimeError(code))),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={"timestamp": "1", "nonce": "2", "signature": signature},
                    get_data=AsyncMock(return_value=b"<xml><broken"),
                ),
            ),
            self.assertRaisesRegex(RuntimeError, "400"),
        ):
            await endpoint(
                path_token="path-token",
                config_provider=lambda: cfg,
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
                client_profile_service_provider=lambda: _ClientProfileServiceStub(),
            )

        ipc_service.handle_ipc_request.assert_not_awaited()

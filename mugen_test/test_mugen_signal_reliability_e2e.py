"""Reliability E2E tests for Signal receive IPC processing."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from sqlalchemy.exc import IntegrityError

from mugen.core.contract.service.ingress_routing import (
    IngressRouteResolution,
    IngressRouteResult,
)
from mugen.core.contract.service.ipc import IPCCommandRequest
from mugen.core.plugin.signal.restapi.ipc_ext import SignalRestAPIIPCExtension
from mugen.core.service.ipc import DefaultIPCService

_CLIENT_PROFILE_ID = uuid.UUID("00000000-0000-0000-0000-000000000205")


class _MemoryRelational:
    def __init__(self) -> None:
        self.event_dedup: dict[tuple[str, str], dict] = {}
        self.dead_letters: list[dict] = []

    async def insert_one(self, table: str, record: dict):
        if table == "signal_restapi_event_dedup":
            key = (record["event_type"], record["dedupe_key"])
            if key in self.event_dedup:
                raise IntegrityError("insert", {}, Exception("duplicate"))
            self.event_dedup[key] = dict(record)
            return dict(record)
        if table == "signal_restapi_event_dead_letter":
            self.dead_letters.append(dict(record))
            return dict(record)
        raise ValueError(f"Unsupported table: {table}")

    async def update_one(self, table: str, where: dict, changes: dict):
        if table != "signal_restapi_event_dedup":
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
            platforms=["signal"],
            runtime=SimpleNamespace(
                profile="platform_full",
                provider_readiness_timeout_seconds=15.0,
                provider_shutdown_timeout_seconds=10.0,
                shutdown_timeout_seconds=60.0,
                phase_b=SimpleNamespace(startup_timeout_seconds=30.0),
            ),
        ),
        signal=SimpleNamespace(
            receive=SimpleNamespace(dedupe_ttl_seconds=86400),
            typing=SimpleNamespace(enabled=True),
        ),
    )


def _make_client() -> SimpleNamespace:
    return SimpleNamespace(
        send_text_message=AsyncMock(return_value={"ok": True, "status": 200, "data": {}}),
        send_media_message=AsyncMock(return_value={"ok": True, "status": 200, "data": {}}),
        send_reaction=AsyncMock(return_value={"ok": True, "status": 200, "data": {}}),
        send_receipt=AsyncMock(return_value={"ok": True, "status": 200, "data": {}}),
        emit_processing_signal=AsyncMock(return_value=True),
        download_attachment=AsyncMock(
            return_value={
                "path": "/tmp/file.bin",
                "mime_type": "application/octet-stream",
            }
        ),
    )


class _IngressRoutingStub:
    async def resolve(self, request) -> IngressRouteResolution:
        identifier_value = request.identifier_value
        if not isinstance(identifier_value, str) or identifier_value.strip() == "":
            identifier_value = "+15550000"
        return IngressRouteResolution(
            ok=True,
            result=IngressRouteResult(
                tenant_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
                tenant_slug="tenant-a",
                platform="signal",
                channel_key="signal",
                client_profile_id=_CLIENT_PROFILE_ID,
                client_profile_key="signal-a",
                identifier_claims={
                    "identifier_type": "account_number",
                    "identifier_value": str(identifier_value),
                },
            ),
        )


def _new_extension(
    *,
    logger: Mock,
    relational_gateway: _MemoryRelational,
    messaging_service: SimpleNamespace,
    user_service: SimpleNamespace,
    client: SimpleNamespace,
) -> SignalRestAPIIPCExtension:
    return SignalRestAPIIPCExtension(
        config=_make_config(),
        logging_gateway=logger,
        relational_storage_gateway=relational_gateway,
        messaging_service=messaging_service,
        user_service=user_service,
        signal_client=client,
        ingress_routing_service=_IngressRoutingStub(),
    )


def _new_ipc_service(*, logger: Mock, ipc_ext: SignalRestAPIIPCExtension) -> DefaultIPCService:
    ipc_service = DefaultIPCService(
        config=SimpleNamespace(),
        logging_gateway=logger,
    )
    ipc_service.bind_ipc_extension(ipc_ext)
    return ipc_service


def _make_text_event(*, text: str = "hello") -> dict:
    return {
        "method": "receive",
        "params": {
            "envelope": {
                "sourceNumber": "+15550001",
                "sourceUuid": "src-uuid-1",
                "timestamp": 1001,
                "dataMessage": {
                    "message": text,
                },
            }
        },
    }


class TestMugenSignalReliabilityE2E(unittest.IsolatedAsyncioTestCase):
    """Exercises dedupe and dead-letter reliability behavior for Signal IPC."""

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
            get_known_users_list=AsyncMock(return_value={"+15550001": "Known User"}),
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
        payload = _make_text_event(text="hello")
        request = IPCCommandRequest(
            platform="signal",
            command="signal_restapi_event",
            data=payload,
        )

        first = await ipc_service.handle_ipc_request(request)
        second = await ipc_service.handle_ipc_request(request)

        self.assertEqual(first.errors, [])
        self.assertEqual(second.errors, [])
        self.assertEqual(first.received, 1)
        self.assertEqual(second.received, 1)
        messaging_service.handle_text_message.assert_awaited_once_with(
            "signal",
            room_id="+15550001",
            sender="+15550001",
            message="hello",
            message_context=[
                {
                    "type": "ingress_route",
                    "content": {
                        "tenant_id": "11111111-1111-1111-1111-111111111111",
                        "tenant_slug": "tenant-a",
                        "platform": "signal",
                        "channel_key": "signal",
                        "identifier_claims": {
                            "identifier_type": "account_number",
                            "identifier_value": "+15550000",
                        },
                        "channel_profile_id": None,
                        "service_route_key": None,
                        "route_key": None,
                        "binding_id": None,
                        "client_profile_id": str(_CLIENT_PROFILE_ID),
                        "client_profile_key": "signal-a",
                        "tenant_resolution": {
                            "mode": "resolved",
                            "reason_code": None,
                            "source": "signal.ingress_routing",
                        },
                    },
                }
            ],
        )

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
            get_known_users_list=AsyncMock(return_value={"+15550001": "Known User"}),
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
        request = IPCCommandRequest(
            platform="signal",
            command="signal_restapi_event",
            data=_make_text_event(text="explode"),
        )

        result = await ipc_service.handle_ipc_request(request)
        self.assertEqual(len(result.errors), 1)

        self.assertEqual(len(relational_gateway.dead_letters), 1)
        dead_letter = relational_gateway.dead_letters[0]
        self.assertEqual(dead_letter["event_type"], "message")
        self.assertEqual(dead_letter["reason_code"], "processing_exception")
        self.assertIn("RuntimeError: boom", dead_letter["error_message"])

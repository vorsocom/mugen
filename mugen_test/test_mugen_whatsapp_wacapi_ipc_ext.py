"""Unit tests for mugen.core.plugin.whatsapp.wacapi.ipc_ext."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import ANY, AsyncMock, Mock, patch
import uuid

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mugen.core.contract.service.ingress_routing import (
    IngressRouteReason,
    IngressRouteResolution,
    IngressRouteResult,
)
from mugen.core.contract.service.ipc import IPCCommandRequest
from mugen.core.plugin.whatsapp.wacapi import ipc_ext
from mugen.core.plugin.whatsapp.wacapi.ipc_ext import WhatsAppWACAPIIPCExtension
from mugen.core.utility.messaging_client_user_access import (
    MessagingClientUserAccessPolicy,
)

_CLIENT_PROFILE_ID = uuid.UUID("00000000-0000-0000-0000-000000000204")


def _make_config(
    *,
    beta_active: bool,
    beta_users=None,
    beta_message: str = "Beta only",
    access_mode: str | None = None,
    access_users=None,
    denied_message: str | None = None,
):
    if access_mode is None:
        access_mode = "allow-only" if beta_active else "allow-all"
    if access_users is None:
        access_users = beta_users
    if denied_message is None and beta_active:
        denied_message = beta_message
    return SimpleNamespace(
        whatsapp=SimpleNamespace(
            user_access=SimpleNamespace(
                mode=access_mode,
                users=list(access_users or []),
                denied_message=denied_message,
            ),
            business=SimpleNamespace(phone_number_id="pnid-1"),
        ),
    )


def _make_message_event(message: dict, sender: str = "15550001") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [
                                {
                                    "wa_id": sender,
                                    "profile": {"name": "Test User"},
                                }
                            ],
                            "messages": [message],
                        }
                    }
                ]
            }
        ]
    }


def _make_status_event(status: dict) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [status],
                        }
                    }
                ]
            }
        ]
    }


def _make_request(
    data: dict,
    command: str = "whatsapp_wacapi_event",
) -> IPCCommandRequest:
    return IPCCommandRequest(
        platform="whatsapp",
        command=command,
        data=data,
    )


def _make_messaging_service():
    return SimpleNamespace(
        handle_audio_message=AsyncMock(return_value=[]),
        handle_file_message=AsyncMock(return_value=[]),
        handle_image_message=AsyncMock(return_value=[]),
        handle_text_message=AsyncMock(return_value=[]),
        handle_video_message=AsyncMock(return_value=[]),
        mh_extensions=[],
    )


def _make_client():
    return SimpleNamespace(
        retrieve_media_url=AsyncMock(
            return_value=_ok_payload({"url": "https://media.example"})
        ),
        download_media=AsyncMock(return_value="/tmp/file.bin"),
        upload_media=AsyncMock(return_value=_ok_payload({"id": "media-id"})),
        send_audio_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m1"}]})
        ),
        send_contacts_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m2"}]})
        ),
        send_document_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m3"}]})
        ),
        send_image_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m4"}]})
        ),
        send_interactive_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m5"}]})
        ),
        send_location_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m6"}]})
        ),
        send_reaction_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m7"}]})
        ),
        send_sticker_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m8"}]})
        ),
        send_template_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m9"}]})
        ),
        send_text_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m10"}]})
        ),
        send_video_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m11"}]})
        ),
        emit_processing_signal=AsyncMock(return_value=True),
        user_access_policy=AsyncMock(return_value=MessagingClientUserAccessPolicy()),
    )


def _make_user_service(known_users=None):
    return SimpleNamespace(
        get_known_users_list=AsyncMock(return_value=dict(known_users or {})),
        add_known_user=AsyncMock(),
    )


class _MemoryRelational:
    def __init__(self):
        self.event_dedup: dict[tuple[str, str], dict] = {}
        self.dead_letters: list[dict] = []

    async def insert_one(self, table: str, record: dict) -> dict:
        if table == "whatsapp_wacapi_event_dedup":
            key = (record["event_type"], record["dedupe_key"])
            if key in self.event_dedup:
                raise IntegrityError("insert", {}, Exception("duplicate"))
            self.event_dedup[key] = dict(record)
            return dict(record)
        if table == "whatsapp_wacapi_event_dead_letter":
            self.dead_letters.append(dict(record))
            return dict(record)
        raise ValueError(f"Unsupported table: {table}")

    async def update_one(self, table: str, where: dict, changes: dict) -> dict | None:
        if table != "whatsapp_wacapi_event_dedup":
            raise ValueError(f"Unsupported table: {table}")
        key = (where.get("event_type"), where.get("dedupe_key"))
        existing = self.event_dedup.get(key)
        if existing is None:
            return None
        existing.update(changes)
        return dict(existing)


class _IngressRoutingStub:
    async def resolve(self, request) -> IngressRouteResolution:
        identifier_value = request.identifier_value
        if not isinstance(identifier_value, str) or identifier_value.strip() == "":
            identifier_value = "pnid-1"
        return IngressRouteResolution(
            ok=True,
            result=IngressRouteResult(
                tenant_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
                tenant_slug="tenant-a",
                platform="whatsapp",
                channel_key="whatsapp",
                client_profile_id=_CLIENT_PROFILE_ID,
                client_profile_key="whatsapp-a",
                identifier_claims={
                    "identifier_type": "phone_number_id",
                    "identifier_value": str(identifier_value),
                },
            ),
        )


def _new_extension(
    *,
    config,
    client=None,
    relational_storage_gateway=None,
    messaging_service=None,
    user_service=None,
    logging_gateway=None,
    ingress_routing_service=None,
) -> WhatsAppWACAPIIPCExtension:
    return WhatsAppWACAPIIPCExtension(
        config=config,
        logging_gateway=logging_gateway or Mock(),
        relational_storage_gateway=(
            relational_storage_gateway or _MemoryRelational()
        ),
        messaging_service=messaging_service or _make_messaging_service(),
        user_service=user_service or _make_user_service(),
        whatsapp_client=client or _make_client(),
        ingress_routing_service=ingress_routing_service or _IngressRoutingStub(),
    )


class _MhExtension:
    def __init__(self, *, supported: bool, message_types: list[str]):
        self._supported = supported
        self.message_types = message_types
        self.handle_message = AsyncMock(
            return_value=[{"type": "text", "content": "ok"}]
        )

    def platform_supported(self, _platform: str) -> bool:
        return self._supported


class TestMugenWhatsAppWacapiIpcExt(unittest.IsolatedAsyncioTestCase):
    """Covers event routing, media processing, and message-handler fallback paths."""

    async def test_properties_and_process_command_dispatch(self) -> None:
        ext = _new_extension(config=_make_config(beta_active=False))

        self.assertEqual(ext.platforms, ["whatsapp"])
        self.assertEqual(
            ext.ipc_commands,
            ["whatsapp_ingress_event", "whatsapp_wacapi_event"],
        )

        with (
            patch.object(ext, "_whatsapp_ingress_event", new=AsyncMock()) as ingress_handler,
            patch.object(ext, "_wacapi_event", new=AsyncMock()) as event_handler,
        ):
            handled_ingress = await ext.process_ipc_command(
                _make_request(
                    {},
                    command="whatsapp_ingress_event",
                )
            )
            handled = await ext.process_ipc_command(
                _make_request(
                    {},
                    command="whatsapp_wacapi_event",
                )
            )
            unknown = await ext.process_ipc_command(
                _make_request(
                    {},
                    command="unknown",
                )
            )

        ingress_handler.assert_awaited_once()
        event_handler.assert_awaited_once()
        self.assertEqual(handled_ingress.response, {"response": "OK"})
        self.assertTrue(handled_ingress.ok)
        self.assertEqual(handled.response, {"response": "OK"})
        self.assertTrue(handled.ok)
        self.assertFalse(unknown.ok)
        self.assertEqual(unknown.code, "not_found")

    async def test_whatsapp_ingress_event_validates_and_dispatches_message_and_status(
        self,
    ) -> None:
        ext = _new_extension(config=_make_config(beta_active=False))

        with self.assertRaisesRegex(TypeError, "payload.event must be a dict"):
            await ext._whatsapp_ingress_event(  # pylint: disable=protected-access
                _make_request({"payload": []}, command="whatsapp_ingress_event")
            )

        ext._resolve_ingress_route = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            return_value={"client_profile_id": _CLIENT_PROFILE_ID, "tenant_id": "tenant-a"}
        )
        ext._process_message_event = AsyncMock()  # type: ignore[method-assign]  # pylint: disable=protected-access
        ext._process_status_event = AsyncMock()  # type: ignore[method-assign]  # pylint: disable=protected-access

        await ext._whatsapp_ingress_event(  # pylint: disable=protected-access
            _make_request(
                {
                    "client_profile_id": str(_CLIENT_PROFILE_ID),
                    "payload": {
                        "event_value": {"messages": [{"id": "wamid-1"}]},
                        "message": {"id": "wamid-1", "from": "15550001"},
                    },
                    "provider_context": {"phone_number_id": "phone-1", "ingress_route": {}},
                },
                command="whatsapp_ingress_event",
            )
        )
        ext._process_message_event.assert_awaited_once()

        await ext._whatsapp_ingress_event(  # pylint: disable=protected-access
            _make_request(
                {
                    "client_profile_id": str(_CLIENT_PROFILE_ID),
                    "payload": {
                        "status": {"id": "status-1", "recipient_id": "15550002"},
                    },
                    "provider_context": {"phone_number_id": "phone-1", "ingress_route": {}},
                },
                command="whatsapp_ingress_event",
            )
        )
        ext._process_status_event.assert_awaited_once()

        ext._process_message_event.reset_mock()
        ext._process_status_event.reset_mock()
        await ext._whatsapp_ingress_event(  # pylint: disable=protected-access
            _make_request(
                {
                    "client_profile_id": str(_CLIENT_PROFILE_ID),
                    "payload": {"event_value": {}},
                    "provider_context": {"phone_number_id": "phone-1", "ingress_route": {}},
                },
                command="whatsapp_ingress_event",
            )
        )
        ext._process_message_event.assert_not_awaited()
        ext._process_status_event.assert_not_awaited()

        ext._process_message_event.reset_mock()
        ext._process_status_event.reset_mock()
        ext._resolve_ingress_route = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            return_value=None
        )
        await ext._whatsapp_ingress_event(  # pylint: disable=protected-access
            _make_request(
                {
                    "payload": {
                        "event_value": {},
                    },
                    "provider_context": {"phone_number_id": "phone-1", "ingress_route": {}},
                },
                command="whatsapp_ingress_event",
            )
        )
        ext._process_message_event.assert_not_awaited()
        ext._process_status_event.assert_not_awaited()

        ext._resolve_ingress_route.reset_mock()  # type: ignore[union-attr]
        await ext._whatsapp_ingress_event(  # pylint: disable=protected-access
            _make_request(
                {
                    "payload": {
                        "status": {"id": "status-2", "recipient_id": "15550003"},
                    },
                    "provider_context": {
                        "phone_number_id": "phone-1",
                        "ingress_route": {"client_profile_id": str(_CLIENT_PROFILE_ID)},
                    },
                },
                command="whatsapp_ingress_event",
            )
        )
        ext._resolve_ingress_route.assert_not_awaited()  # type: ignore[union-attr]

    async def test_provider_helpers_return_from_di_container_and_emit_skip_branch(
        self,
    ) -> None:
        container = SimpleNamespace(
            whatsapp_client="client",
            config="config",
            logging_gateway="logger",
            relational_storage_gateway="rsg",
            messaging_service="ms",
            user_service="us",
        )

        with patch.object(ipc_ext.di, "container", container):
            self.assertEqual(ipc_ext._whatsapp_client_provider(), "client")
            self.assertEqual(ipc_ext._config_provider(), "config")
            self.assertEqual(ipc_ext._logging_gateway_provider(), "logger")
            self.assertEqual(ipc_ext._relational_storage_gateway_provider(), "rsg")
            self.assertEqual(ipc_ext._messaging_service_provider(), "ms")
            self.assertEqual(ipc_ext._user_service_provider(), "us")

        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=SimpleNamespace(),
        )
        await ext._emit_processing_signal(  # pylint: disable=protected-access
            sender="15550000",
            message_id="mid-1",
            state="start",
        )

    async def test_extract_api_data_handles_missing_failed_and_non_dict(self) -> None:
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            logging_gateway=logging_gateway,
        )

        self.assertIsNone(
            ext._extract_api_data(None, "ctx")
        )  # pylint: disable=protected-access
        self.assertIsNone(
            ext._extract_api_data(
                {"ok": False, "error": "boom", "raw": '{"error":"boom"}'}, "ctx"
            )  # pylint: disable=protected-access
        )
        self.assertIsNone(
            ext._extract_api_data(
                {"ok": False, "error": "", "raw": ""}, "ctx"
            )  # pylint: disable=protected-access
        )
        self.assertIsNone(
            ext._extract_api_data(
                {"ok": True, "data": []}, "ctx"
            )  # pylint: disable=protected-access
        )
        self.assertIsNone(
            ext._extract_api_data("bad", "ctx")
        )  # pylint: disable=protected-access
        self.assertEqual(
            ext._extract_api_data({"ok": True, "data": None}, "ctx"), {}
        )  # pylint: disable=protected-access

        logging_gateway.error.assert_any_call("Missing payload for ctx.")
        logging_gateway.error.assert_any_call("ctx failed.")
        logging_gateway.error.assert_any_call("boom")
        logging_gateway.error.assert_any_call('{"error":"boom"}')
        logging_gateway.error.assert_any_call("Unexpected payload type for ctx.")

    def test_extract_user_text_covers_fallback_and_nfm_paths(self) -> None:
        self.assertEqual(
            WhatsAppWACAPIIPCExtension._extract_user_text(
                {
                    "type": "button",
                    "button": {"payload": "payload-only"},
                }
            ),
            "payload-only",
        )
        self.assertEqual(
            WhatsAppWACAPIIPCExtension._extract_user_text(
                {
                    "type": "interactive",
                    "interactive": {
                        "type": "button_reply",
                        "button_reply": {"id": "btn-id"},
                    },
                }
            ),
            "btn-id",
        )
        self.assertEqual(
            WhatsAppWACAPIIPCExtension._extract_user_text(
                {
                    "type": "interactive",
                    "interactive": {
                        "type": "list_reply",
                        "list_reply": {"title": "List title", "id": "list-1"},
                    },
                }
            ),
            "List title",
        )
        self.assertEqual(
            WhatsAppWACAPIIPCExtension._extract_user_text(
                {
                    "type": "interactive",
                    "interactive": {
                        "type": "list_reply",
                        "list_reply": {"id": "list-only-id"},
                    },
                }
            ),
            "list-only-id",
        )
        self.assertEqual(
            WhatsAppWACAPIIPCExtension._extract_user_text(
                {
                    "type": "interactive",
                    "interactive": {
                        "type": "nfm_reply",
                        "nfm_reply": {"response_json": {"a": 1}},
                    },
                }
            ),
            '{"a": 1}',
        )
        self.assertEqual(
            WhatsAppWACAPIIPCExtension._extract_user_text(
                {
                    "type": "interactive",
                    "interactive": {
                        "type": "nfm_reply",
                        "nfm_reply": {"response_json": '{"a":1}'},
                    },
                }
            ),
            '{"a":1}',
        )
        self.assertIsNone(
            WhatsAppWACAPIIPCExtension._extract_user_text(
                {
                    "type": "interactive",
                    "interactive": {
                        "type": "nfm_reply",
                        "nfm_reply": {"response_json": [1, 2]},
                    },
                }
            )
        )
        self.assertIsNone(
            WhatsAppWACAPIIPCExtension._extract_user_text(
                {
                    "type": "audio",
                }
            )
        )
        self.assertIsNone(
            WhatsAppWACAPIIPCExtension._extract_user_text(
                {
                    "type": "interactive",
                    "interactive": {"type": "unknown"},
                }
            )
        )

    def test_extract_flow_reply_metadata_detects_nfm_reply(self) -> None:
        self.assertEqual(
            WhatsAppWACAPIIPCExtension._extract_flow_reply_metadata(
                {
                    "type": "interactive",
                    "interactive": {
                        "type": "nfm_reply",
                        "nfm_reply": {
                            "flow_token": "flow-token-1",
                            "flow_name": "booking_lookup",
                            "response_json": {"quote_id": "q-1"},
                        },
                    },
                }
            ),
            {
                "type": "nfm_reply",
                "flow_token": "flow-token-1",
                "flow_name": "booking_lookup",
                "response_json": {"quote_id": "q-1"},
            },
        )
        self.assertIsNone(
            WhatsAppWACAPIIPCExtension._extract_flow_reply_metadata(
                {
                    "type": "interactive",
                    "interactive": {"type": "button_reply"},
                }
            )
        )
        self.assertIsNone(
            WhatsAppWACAPIIPCExtension._extract_flow_reply_metadata(
                {
                    "type": "interactive",
                    "interactive": {
                        "type": "nfm_reply",
                        "nfm_reply": "bad-payload",
                    },
                }
            )
        )

    async def test_user_access_policy_replies_and_returns_early(self) -> None:
        client = _make_client()
        client.user_access_policy.return_value = MessagingClientUserAccessPolicy(
            mode="allow-only",
            users=("15550002",),
            denied_message="Not enabled",
        )
        messaging_service = _make_messaging_service()
        user_service = _make_user_service()
        ext = _new_extension(
            config=_make_config(
                beta_active=False,
                access_mode="allow-only",
                access_users=["15550002"],
                denied_message="Not enabled",
            ),
            client=client,
            messaging_service=messaging_service,
            user_service=user_service,
        )
        payload = _make_request(
            _make_message_event(
                {
                    "id": "wamid-1",
                    "type": "text",
                    "text": {"body": "hello"},
                },
                sender="15550001",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        client.send_text_message.assert_awaited_once_with(
            message="Not enabled",
            recipient="15550001",
        )
        messaging_service.handle_text_message.assert_not_awaited()
        user_service.add_known_user.assert_not_awaited()

    async def test_user_access_policy_denies_without_reply_when_no_message(self) -> None:
        client = _make_client()
        client.user_access_policy.return_value = MessagingClientUserAccessPolicy(
            mode="allow-only",
            users=("15550002",),
            denied_message=None,
        )
        messaging_service = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(
                beta_active=False,
                access_mode="allow-only",
                access_users=["15550002"],
            ),
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(),
        )

        await ext._process_message_event(  # pylint: disable=protected-access
            {
                "contacts": [
                    {
                        "wa_id": "15550001",
                        "profile": {"name": "Test User"},
                    }
                ]
            },
            {
                "id": "wamid-no-reply",
                "from": "15550001",
                "type": "text",
                "text": {"body": "hello"},
            },
            {},
            skip_dedupe=True,
        )

        client.send_text_message.assert_not_awaited()
        messaging_service.handle_text_message.assert_not_awaited()

    async def test_invalid_user_access_policy_is_logged_and_dropped(self) -> None:
        client = _make_client()
        client.user_access_policy.return_value = "invalid"
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            messaging_service=_make_messaging_service(),
            user_service=_make_user_service(),
        )

        await ext._process_message_event(  # pylint: disable=protected-access
            {
                "contacts": [
                    {
                        "wa_id": "15550001",
                        "profile": {"name": "Test User"},
                    }
                ]
            },
            {
                "id": "wamid-invalid-policy",
                "from": "15550001",
                "type": "text",
                "text": {"body": "hello"},
            },
            {},
            skip_dedupe=True,
        )

        client.send_text_message.assert_not_awaited()
        self.assertIn(
            "Invalid user access policy",
            ext._logging_gateway.warning.call_args.args[0],  # pylint: disable=protected-access
        )

    async def test_resolve_user_access_policy_handles_none_and_invalid_results(self) -> None:
        client = _make_client()
        client.user_access_policy.return_value = None
        ext = _new_extension(config=_make_config(beta_active=False), client=client)

        policy = await ext._resolve_user_access_policy()  # pylint: disable=protected-access
        self.assertEqual(policy, MessagingClientUserAccessPolicy())

        client.user_access_policy.return_value = "invalid"
        with self.assertRaisesRegex(RuntimeError, "returned an invalid result"):
            await ext._resolve_user_access_policy()  # pylint: disable=protected-access

    async def test_text_event_processes_and_sends_all_response_types(self) -> None:
        client = _make_client()
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(
            return_value=[
                {
                    "type": "audio",
                    "file": {"uri": "/tmp/out.ogg", "type": "audio/ogg"},
                },
                {
                    "type": "file",
                    "file": {
                        "uri": "/tmp/out.pdf",
                        "type": "application/pdf",
                        "name": "out.pdf",
                    },
                },
                {
                    "type": "image",
                    "file": {"uri": "/tmp/out.png", "type": "image/png"},
                },
                {"type": "text", "content": "hello back"},
                {
                    "type": "video",
                    "file": {"uri": "/tmp/out.mp4", "type": "video/mp4"},
                },
            ]
        )
        user_service = _make_user_service(known_users={})
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            messaging_service=messaging_service,
            user_service=user_service,
        )
        payload = _make_request(
            _make_message_event(
                {
                    "id": "wamid-2",
                    "type": "text",
                    "text": {"body": "incoming"},
                },
                sender="15550003",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        messaging_service.handle_text_message.assert_awaited_once_with(
            "whatsapp",
            room_id="15550003",
            sender="15550003",
            message="incoming",
            message_context=ANY,
            ingress_metadata=ANY,
            message_id="wamid-2",
        )
        user_service.add_known_user.assert_awaited_once_with(
            "15550003",
            "Test User",
            "15550003",
        )
        self.assertEqual(client.upload_media.await_count, 4)
        client.send_audio_message.assert_awaited_once()
        client.send_document_message.assert_awaited_once()
        client.send_image_message.assert_awaited_once()
        self.assertGreaterEqual(client.send_text_message.await_count, 1)
        client.send_video_message.assert_awaited_once()
        client.emit_processing_signal.assert_any_await(
            "15550003",
            state="start",
            message_id="wamid-2",
        )
        client.emit_processing_signal.assert_any_await(
            "15550003",
            state="stop",
            message_id="wamid-2",
        )

    async def test_processing_signal_failure_does_not_block_message_processing(
        self,
    ) -> None:
        client = _make_client()
        client.emit_processing_signal = AsyncMock(side_effect=RuntimeError("boom"))
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(return_value=[])
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            messaging_service=messaging_service,
            logging_gateway=logging_gateway,
        )

        await ext._process_message_event(  # pylint: disable=protected-access
            {"contacts": [{"wa_id": "15550001"}]},
            {
                "id": "wamid-thinking-error",
                "from": "15550001",
                "type": "text",
                "text": {"body": "hello"},
            },
        )

        messaging_service.handle_text_message.assert_awaited_once_with(
            "whatsapp",
            room_id="15550001",
            sender="15550001",
            message="hello",
            message_context=ANY,
            ingress_metadata=ANY,
            message_id="wamid-thinking-error",
        )
        warning_messages = [
            call.args[0] for call in logging_gateway.warning.call_args_list
        ]
        self.assertTrue(
            any("thinking signal raised unexpectedly" in message for message in warning_messages)
        )

    async def test_processing_signal_false_result_logs_warning(self) -> None:
        client = _make_client()
        client.emit_processing_signal = AsyncMock(return_value=False)
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(return_value=[])
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            messaging_service=messaging_service,
            logging_gateway=logging_gateway,
        )

        await ext._process_message_event(  # pylint: disable=protected-access
            {"contacts": [{"wa_id": "15550001"}]},
            {
                "id": "wamid-thinking-false",
                "from": "15550001",
                "type": "text",
                "text": {"body": "hello"},
            },
        )

        warning_messages = [
            call.args[0] for call in logging_gateway.warning.call_args_list
        ]
        self.assertTrue(
            any("thinking signal reported failure" in message for message in warning_messages)
        )

    async def test_processing_signal_stop_emits_when_handler_raises(self) -> None:
        client = _make_client()
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(
            side_effect=RuntimeError("handler boom")
        )
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            messaging_service=messaging_service,
        )

        with self.assertRaises(RuntimeError):
            await ext._process_message_event(  # pylint: disable=protected-access
                {"contacts": [{"wa_id": "15550001"}]},
                {
                    "id": "wamid-handler-error",
                    "from": "15550001",
                    "type": "text",
                    "text": {"body": "hello"},
                },
            )

        client.emit_processing_signal.assert_any_await(
            "15550001",
            state="start",
            message_id="wamid-handler-error",
        )
        client.emit_processing_signal.assert_any_await(
            "15550001",
            state="stop",
            message_id="wamid-handler-error",
        )

    async def test_text_event_processes_extended_response_types(self) -> None:
        client = _make_client()
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(
            return_value=[
                {
                    "type": "contacts",
                    "contacts": [{"name": {"formatted_name": "A"}}],
                },
                {
                    "type": "location",
                    "location": {"latitude": 59.4, "longitude": 24.7},
                },
                {
                    "type": "interactive",
                    "interactive": {"type": "button", "body": {"text": "Choose"}},
                },
                {
                    "type": "template",
                    "template": {
                        "name": "welcome_template",
                        "language": {"code": "en_US"},
                    },
                },
                {
                    "type": "sticker",
                    "sticker": {"id": "sticker-id"},
                },
                {
                    "type": "reaction",
                    "reaction": {"message_id": "mid-1", "emoji": "👍"},
                },
            ]
        )
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"15550031": "known"}),
        )
        payload = _make_request(
            _make_message_event(
                {
                    "id": "wamid-extended",
                    "type": "text",
                    "text": {"body": "incoming"},
                },
                sender="15550031",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        client.send_contacts_message.assert_awaited_once()
        client.send_location_message.assert_awaited_once()
        client.send_interactive_message.assert_awaited_once()
        client.send_template_message.assert_awaited_once()
        client.send_sticker_message.assert_awaited_once()
        client.send_reaction_message.assert_awaited_once()
        self.assertEqual(client.upload_media.await_count, 0)

    async def test_interactive_and_button_messages_route_to_text_handler(self) -> None:
        cases = [
            (
                {
                    "id": "wamid-i1",
                    "type": "interactive",
                    "interactive": {
                        "type": "button_reply",
                        "button_reply": {"id": "btn-1", "title": "Option 1"},
                    },
                },
                "Option 1",
            ),
            (
                {
                    "id": "wamid-i2",
                    "type": "button",
                    "button": {"payload": "payload-2", "text": "Button 2"},
                },
                "Button 2",
            ),
        ]

        for incoming_message, expected_text in cases:
            with self.subTest(expected_text=expected_text):
                client = _make_client()
                messaging_service = _make_messaging_service()
                ext = _new_extension(
                    config=_make_config(beta_active=False),
                    client=client,
                    messaging_service=messaging_service,
                    user_service=_make_user_service(known_users={"15550088": "known"}),
                )
                payload = _make_request(
                    _make_message_event(
                        incoming_message,
                        sender="15550088",
                    )
                )

                await ext._wacapi_event(payload)  # pylint: disable=protected-access

                messaging_service.handle_text_message.assert_awaited_once_with(
                    "whatsapp",
                    room_id="15550088",
                    sender="15550088",
                    message=expected_text,
                    message_context=ANY,
                    ingress_metadata=ANY,
                    message_id=incoming_message["id"],
                )

    async def test_text_path_passes_ingress_metadata_and_message_id(self) -> None:
        messaging_service = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"15550123": "known"}),
        )
        payload = _make_request(
            _make_message_event(
                {
                    "id": "wamid-text-metadata",
                    "type": "text",
                    "text": {"body": "hello"},
                },
                sender="15550123",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        call = messaging_service.handle_text_message.await_args
        self.assertEqual(call.args, ("whatsapp",))
        self.assertEqual(call.kwargs["room_id"], "15550123")
        self.assertEqual(call.kwargs["sender"], "15550123")
        self.assertEqual(call.kwargs["message"], "hello")
        self.assertEqual(call.kwargs["message_id"], "wamid-text-metadata")
        ingress_metadata = call.kwargs["ingress_metadata"]
        self.assertIsInstance(ingress_metadata, dict)
        self.assertNotIn("whatsapp_flow_reply", ingress_metadata)
        ingress_route = ingress_metadata["ingress_route"]
        self.assertEqual(ingress_route["platform"], "whatsapp")
        self.assertEqual(ingress_route["channel_key"], "whatsapp")
        self.assertEqual(
            ingress_route["identifier_claims"]["identifier_value"],
            "pnid-1",
        )

    async def test_nfm_reply_keeps_text_fallback_and_attaches_structured_metadata(
        self,
    ) -> None:
        messaging_service = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"15550124": "known"}),
        )
        payload = _make_request(
            _make_message_event(
                {
                    "id": "wamid-flow-1",
                    "type": "interactive",
                    "interactive": {
                        "type": "nfm_reply",
                        "nfm_reply": {
                            "flow_token": "flow-token-9",
                            "flow_name": "booking_quote",
                            "response_json": {"pickup_date": "2026-03-20"},
                        },
                    },
                },
                sender="15550124",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        call = messaging_service.handle_text_message.await_args
        self.assertEqual(call.kwargs["message"], '{"pickup_date": "2026-03-20"}')
        self.assertEqual(call.kwargs["message_id"], "wamid-flow-1")
        self.assertEqual(
            call.kwargs["ingress_metadata"]["whatsapp_flow_reply"],
            {
                "type": "nfm_reply",
                "flow_token": "flow-token-9",
                "flow_name": "booking_quote",
                "response_json": {"pickup_date": "2026-03-20"},
            },
        )
        self.assertIn("ingress_route", call.kwargs["ingress_metadata"])

    async def test_button_message_without_extractable_text_delegates_to_handlers(
        self,
    ) -> None:
        ext = _new_extension(config=_make_config(beta_active=False))
        payload = _make_request(
            _make_message_event(
                {
                    "id": "wamid-button-empty",
                    "type": "button",
                    "button": {},
                },
                sender="15550089",
            )
        )

        with patch.object(
            ext, "_call_message_handlers", new=AsyncMock()
        ) as route_handlers:
            await ext._wacapi_event(payload)  # pylint: disable=protected-access

        route_handlers.assert_awaited_once_with(
            message={
                "id": "wamid-button-empty",
                "type": "button",
                "button": {},
            },
            message_type="button",
            sender="15550089",
        )

    async def test_upload_response_media_validates_payload_shapes(self) -> None:
        client = _make_client()
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            logging_gateway=logging_gateway,
        )

        self.assertIsNone(
            await ext._upload_response_media(
                {"type": "audio"}, "audio"
            )  # pylint: disable=protected-access
        )
        self.assertIsNone(
            await ext._upload_response_media(  # pylint: disable=protected-access
                {"type": "audio", "file": {"uri": "/tmp/a.ogg"}},
                "audio",
            )
        )
        logging_gateway.error.assert_any_call(
            "Missing file payload for audio response."
        )
        logging_gateway.error.assert_any_call(
            "Invalid file payload for audio response."
        )

    async def test_send_response_to_user_handles_validation_and_unknown_types(
        self,
    ) -> None:
        client = _make_client()
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            logging_gateway=logging_gateway,
        )

        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "text", "content": "hello", "reply_to": "mid-1"},
            "15550090",
        )
        client.send_text_message.assert_awaited_with(
            message="hello",
            recipient="15550090",
            reply_to="mid-1",
        )

        invalid_cases = [
            {"type": "text"},
            {"type": "location", "content": "bad"},
            {"type": "interactive", "content": "bad"},
            {"type": "template", "content": "bad"},
            {"type": "sticker", "content": "bad"},
            {"type": "reaction", "content": "bad"},
            {"type": "unknown"},
        ]
        for response in invalid_cases:
            await ext._send_response_to_user(  # pylint: disable=protected-access
                response,
                "15550090",
            )

        logging_gateway.error.assert_any_call(
            "Missing text content in response payload."
        )
        logging_gateway.error.assert_any_call("Missing location payload in response.")
        logging_gateway.error.assert_any_call(
            "Missing interactive payload in response."
        )
        logging_gateway.error.assert_any_call("Missing template payload in response.")
        logging_gateway.error.assert_any_call("Missing sticker payload in response.")
        logging_gateway.error.assert_any_call("Missing reaction payload in response.")
        logging_gateway.error.assert_any_call("Unsupported response type: unknown.")

    async def test_send_file_response_without_filename(self) -> None:
        client = _make_client()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
        )

        await ext._send_response_to_user(  # pylint: disable=protected-access
            {
                "type": "file",
                "file": {"uri": "/tmp/out.bin", "type": "application/octet-stream"},
            },
            "15550091",
        )

        client.send_document_message.assert_awaited_once_with(
            document={"id": "media-id"},
            recipient="15550091",
            reply_to=None,
        )

    async def test_media_events_route_to_matching_messaging_handlers(self) -> None:
        cases = [
            ("audio", "audio/mpeg", "handle_audio_message"),
            ("document", "application/pdf", "handle_file_message"),
            ("image", "image/png", "handle_image_message"),
            ("video", "video/mp4", "handle_video_message"),
        ]

        for message_type, mime_type, handler_name in cases:
            with self.subTest(message_type=message_type):
                client = _make_client()
                messaging_service = _make_messaging_service()
                user_service = _make_user_service(known_users={"15550004": "known"})
                ext = _new_extension(
                    config=_make_config(beta_active=False),
                    client=client,
                    messaging_service=messaging_service,
                    user_service=user_service,
                )
                payload = _make_request(
                    _make_message_event(
                        {
                            "id": f"wamid-{message_type}",
                            "type": message_type,
                            message_type: {
                                "id": f"media-{message_type}",
                                "mime_type": mime_type,
                            },
                        },
                        sender="15550004",
                    )
                )

                await ext._wacapi_event(payload)  # pylint: disable=protected-access

                client.retrieve_media_url.assert_awaited_once_with(
                    f"media-{message_type}"
                )
                client.download_media.assert_awaited_once_with(
                    "https://media.example",
                    mime_type,
                )
                getattr(messaging_service, handler_name).assert_awaited_once()

    async def test_media_events_skip_handlers_when_media_lookup_or_download_missing(
        self,
    ) -> None:
        cases = [
            ("audio", "audio/mpeg", "handle_audio_message"),
            ("document", "application/pdf", "handle_file_message"),
            ("image", "image/png", "handle_image_message"),
            ("video", "video/mp4", "handle_video_message"),
        ]

        for mode in ("missing_url", "missing_download"):
            for message_type, mime_type, handler_name in cases:
                with self.subTest(mode=mode, message_type=message_type):
                    client = _make_client()
                    if mode == "missing_url":
                        client.retrieve_media_url = AsyncMock(return_value=None)
                    else:
                        client.retrieve_media_url = AsyncMock(
                            return_value=_ok_payload({"url": "https://media.example"})
                        )
                        client.download_media = AsyncMock(return_value=None)

                    messaging_service = _make_messaging_service()
                    ext = _new_extension(
                        config=_make_config(beta_active=False),
                        client=client,
                        messaging_service=messaging_service,
                        user_service=_make_user_service(
                            known_users={"15550021": "known"}
                        ),
                    )
                    payload = _make_request(
                        _make_message_event(
                            {
                                "id": f"wamid-{mode}-{message_type}",
                                "type": message_type,
                                message_type: {
                                    "id": f"media-{message_type}",
                                    "mime_type": mime_type,
                                },
                            },
                            sender="15550021",
                        )
                    )

                    await ext._wacapi_event(payload)  # pylint: disable=protected-access

                    client.retrieve_media_url.assert_awaited_once_with(
                        f"media-{message_type}"
                    )
                    if mode == "missing_url":
                        client.download_media.assert_not_awaited()
                    else:
                        client.download_media.assert_awaited_once_with(
                            "https://media.example",
                            mime_type,
                        )
                    getattr(messaging_service, handler_name).assert_not_awaited()

    async def test_message_event_fans_out_all_messages(self) -> None:
        messaging_service = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            relational_storage_gateway=_MemoryRelational(),
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"15550100": "known"}),
        )
        payload = _make_request(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "contacts": [
                                        {
                                            "wa_id": "15550100",
                                            "profile": {"name": "Known User"},
                                        }
                                    ],
                                    "messages": [
                                        {
                                            "id": "wamid-fanout-1",
                                            "type": "text",
                                            "text": {"body": "first"},
                                        },
                                        {
                                            "id": "wamid-fanout-2",
                                            "type": "text",
                                            "text": {"body": "second"},
                                        },
                                    ],
                                }
                            }
                        ]
                    }
                ]
            }
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        self.assertEqual(messaging_service.handle_text_message.await_count, 2)
        messaging_service.handle_text_message.assert_any_await(
            "whatsapp",
            room_id="15550100",
            sender="15550100",
            message="first",
            message_context=ANY,
            ingress_metadata=ANY,
            message_id="wamid-fanout-1",
        )
        messaging_service.handle_text_message.assert_any_await(
            "whatsapp",
            room_id="15550100",
            sender="15550100",
            message="second",
            message_context=ANY,
            ingress_metadata=ANY,
            message_id="wamid-fanout-2",
        )

    async def test_status_event_routes_to_message_handlers(self) -> None:
        ext = _new_extension(config=_make_config(beta_active=False))
        payload = _make_request(
            _make_status_event({"id": "st-1", "status": "delivered"})
        )

        with patch.object(
            ext, "_call_message_handlers", new=AsyncMock()
        ) as route_handlers:
            await ext._wacapi_event(payload)  # pylint: disable=protected-access

        route_handlers.assert_awaited_once_with(
            message={"id": "st-1", "status": "delivered"},
            message_type="status",
        )

    async def test_status_event_fans_out_all_statuses(self) -> None:
        ext = _new_extension(config=_make_config(beta_active=False))
        payload = _make_request(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "statuses": [
                                        {"id": "st-fanout-1", "status": "sent"},
                                        {"id": "st-fanout-2", "status": "read"},
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
        )

        with patch.object(
            ext, "_call_message_handlers", new=AsyncMock()
        ) as route_handlers:
            await ext._wacapi_event(payload)  # pylint: disable=protected-access

        self.assertEqual(route_handlers.await_count, 2)
        route_handlers.assert_any_await(
            message={"id": "st-fanout-1", "status": "sent"},
            message_type="status",
        )
        route_handlers.assert_any_await(
            message={"id": "st-fanout-2", "status": "read"},
            message_type="status",
        )

    async def test_malformed_message_item_does_not_block_valid_message(self) -> None:
        logging_gateway = Mock()
        messaging_service = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            relational_storage_gateway=_MemoryRelational(),
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"15550110": "known"}),
            logging_gateway=logging_gateway,
        )
        payload = _make_request(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "contacts": [
                                        {
                                            "wa_id": "15550110",
                                            "profile": {"name": "Known User"},
                                        }
                                    ],
                                    "messages": [
                                        "bad-item",
                                        {
                                            "id": "wamid-good-1",
                                            "type": "text",
                                            "text": {"body": "still processed"},
                                        },
                                    ],
                                }
                            }
                        ]
                    }
                ]
            }
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        logging_gateway.error.assert_any_call("Malformed WhatsApp message payload.")
        messaging_service.handle_text_message.assert_awaited_once_with(
            "whatsapp",
            room_id="15550110",
            sender="15550110",
            message="still processed",
            message_context=ANY,
            ingress_metadata=ANY,
            message_id="wamid-good-1",
        )

    async def test_duplicate_message_event_is_acknowledged_without_reprocessing(
        self,
    ) -> None:
        messaging_service = _make_messaging_service()
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            relational_storage_gateway=_MemoryRelational(),
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"15550044": "known"}),
            logging_gateway=logging_gateway,
        )
        first_payload = _make_request(
            _make_message_event(
                {
                    "id": "wamid-dupe-1",
                    "type": "text",
                    "text": {"body": "hello"},
                },
                sender="15550044",
            )
        )
        second_payload = _make_request(
            _make_message_event(
                {
                    "id": "wamid-dupe-1",
                    "type": "text",
                    "text": {"body": "hello"},
                },
                sender="15550044",
            )
        )

        await ext._wacapi_event(first_payload)  # pylint: disable=protected-access
        await ext._wacapi_event(second_payload)  # pylint: disable=protected-access

        messaging_service.handle_text_message.assert_awaited_once_with(
            "whatsapp",
            room_id="15550044",
            sender="15550044",
            message="hello",
            message_context=ANY,
            ingress_metadata=ANY,
            message_id="wamid-dupe-1",
        )
        logging_gateway.debug.assert_any_call("Skip duplicate WhatsApp message event.")

    async def test_duplicate_status_event_is_acknowledged_without_rerouting(
        self,
    ) -> None:
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            relational_storage_gateway=_MemoryRelational(),
            logging_gateway=logging_gateway,
        )
        first_payload = _make_request(
            _make_status_event({"id": "st-dupe", "status": "delivered"})
        )
        second_payload = _make_request(
            _make_status_event({"id": "st-dupe", "status": "delivered"})
        )

        with patch.object(
            ext, "_call_message_handlers", new=AsyncMock()
        ) as route_handlers:
            await ext._wacapi_event(first_payload)  # pylint: disable=protected-access
            await ext._wacapi_event(second_payload)  # pylint: disable=protected-access

        route_handlers.assert_awaited_once_with(
            message={"id": "st-dupe", "status": "delivered"},
            message_type="status",
        )
        logging_gateway.debug.assert_any_call("Skip duplicate WhatsApp status event.")

    async def test_relational_dedupe_insert_and_duplicate_paths(self) -> None:
        relational = _MemoryRelational()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            relational_storage_gateway=relational,
        )
        self.assertFalse(
            await ext._is_duplicate_event("message", {"id": "evt-1"})  # pylint: disable=protected-access
        )
        self.assertTrue(
            await ext._is_duplicate_event("message", {"id": "evt-1"})  # pylint: disable=protected-access
        )
        self.assertEqual(ext._metrics["whatsapp.ipc.dedupe.miss"], 1)  # pylint: disable=protected-access
        self.assertEqual(ext._metrics["whatsapp.ipc.dedupe.hit"], 1)  # pylint: disable=protected-access

    async def test_resolve_event_dedupe_ttl_seconds_fallback_paths(self) -> None:
        cfg_invalid = _make_config(beta_active=False)
        cfg_invalid.whatsapp.webhook = SimpleNamespace(dedupe_ttl_seconds="invalid")
        ext_invalid = _new_extension(config=cfg_invalid)
        self.assertEqual(
            ext_invalid._event_dedup_ttl_seconds,  # pylint: disable=protected-access
            86400,
        )

        cfg_non_positive = _make_config(beta_active=False)
        cfg_non_positive.whatsapp.webhook = SimpleNamespace(dedupe_ttl_seconds=0)
        ext_non_positive = _new_extension(config=cfg_non_positive)
        self.assertEqual(
            ext_non_positive._event_dedup_ttl_seconds,  # pylint: disable=protected-access
            86400,
        )

    async def test_record_dead_letter_failure_increments_metric(self) -> None:
        class _DeadLetterFailingGateway:
            async def insert_one(self, _table: str, _record: dict) -> dict:
                raise SQLAlchemyError("boom")

            async def update_one(self, _table: str, _where: dict, _changes: dict):
                return None

        logger = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            logging_gateway=logger,
            relational_storage_gateway=_DeadLetterFailingGateway(),
        )

        await ext._record_dead_letter(  # pylint: disable=protected-access
            event_type="webhook",
            event_payload={"id": "x"},
            reason_code="processing_exception",
            error_message="boom",
        )
        self.assertEqual(
            ext._metrics["whatsapp.ipc.dead_letter.write_failure"],  # pylint: disable=protected-access
            1,
        )
        logger.error.assert_called_once()

    async def test_duplicate_event_update_error_is_tolerated(self) -> None:
        class _UpdateFailGateway(_MemoryRelational):
            async def insert_one(self, table: str, record: dict) -> dict:
                if table == "whatsapp_wacapi_event_dedup":
                    raise IntegrityError("insert", {}, Exception("duplicate"))
                return await super().insert_one(table, record)

            async def update_one(self, _table: str, _where: dict, _changes: dict):
                raise SQLAlchemyError("update-failed")

        ext = _new_extension(
            config=_make_config(beta_active=False),
            relational_storage_gateway=_UpdateFailGateway(),
        )
        self.assertTrue(
            await ext._is_duplicate_event("message", {"id": "evt-1"})  # pylint: disable=protected-access
        )
        self.assertEqual(ext._metrics["whatsapp.ipc.dedupe.hit"], 1)  # pylint: disable=protected-access

    async def test_duplicate_event_storage_error_is_recorded(self) -> None:
        class _InsertFailGateway:
            async def insert_one(self, _table: str, _record: dict) -> dict:
                raise SQLAlchemyError("insert-failed")

            async def update_one(self, _table: str, _where: dict, _changes: dict):
                return None

        logger = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            logging_gateway=logger,
            relational_storage_gateway=_InsertFailGateway(),
        )
        self.assertFalse(
            await ext._is_duplicate_event("message", {"id": "evt-1"})  # pylint: disable=protected-access
        )
        self.assertEqual(
            ext._metrics["whatsapp.ipc.dedupe.error"],  # pylint: disable=protected-access
            1,
        )
        logger.error.assert_called_once()

    async def test_wacapi_event_handles_non_dict_request_payload(self) -> None:
        logger = Mock()
        relational = _MemoryRelational()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            logging_gateway=logger,
            relational_storage_gateway=relational,
        )
        await ext._wacapi_event(  # pylint: disable=protected-access
            IPCCommandRequest(
                platform="whatsapp",
                command="whatsapp_wacapi_event",
                data=[],  # type: ignore[arg-type]
            )
        )
        self.assertEqual(
            ext._metrics["whatsapp.ipc.event.malformed"],  # pylint: disable=protected-access
            1,
        )
        self.assertEqual(relational.dead_letters[0]["reason_code"], "malformed_payload")
        logger.error.assert_any_call("Malformed WhatsApp event payload.")

    async def test_wacapi_event_processing_exception_records_dead_letter(self) -> None:
        logger = Mock()
        relational = _MemoryRelational()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            logging_gateway=logger,
            relational_storage_gateway=relational,
        )
        payload = _make_request(
            _make_message_event(
                {
                    "id": "wamid-crash",
                    "type": "text",
                    "text": {"body": "hello"},
                }
            )
        )
        with patch.object(
            ext,
            "_process_message_event",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            await ext._wacapi_event(payload)  # pylint: disable=protected-access

        self.assertEqual(
            ext._metrics["whatsapp.ipc.event.processed_failed"],  # pylint: disable=protected-access
            1,
        )
        self.assertEqual(
            relational.dead_letters[-1]["reason_code"],
            "processing_exception",
        )
        logger.error.assert_any_call(
            "Unhandled WhatsApp event processing failure."
            " error=RuntimeError: boom"
        )

    def test_get_contact_for_sender_edge_paths(self) -> None:
        ext = _new_extension(config=_make_config(beta_active=False))

        self.assertIsNone(
            ext._get_contact_for_sender(
                None, "15550001"
            )  # pylint: disable=protected-access
        )
        self.assertEqual(
            ext._get_contact_for_sender(  # pylint: disable=protected-access
                [{"wa_id": "15550001"}, {"wa_id": "15550002"}, "bad"],
                "15550002",
            ),
            {"wa_id": "15550002"},
        )
        self.assertIsNone(
            ext._get_contact_for_sender(
                ["bad", 1], "15550003"
            )  # pylint: disable=protected-access
        )

    async def test_process_message_event_without_sender_logs_malformed(self) -> None:
        logging_gateway = Mock()
        messaging_service = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            relational_storage_gateway=_MemoryRelational(),
            messaging_service=messaging_service,
            logging_gateway=logging_gateway,
        )

        await ext._process_message_event(  # pylint: disable=protected-access
            {"contacts": ["bad-contact"]},
            {
                "id": "wamid-no-sender",
                "type": "text",
                "text": {"body": "hello"},
            },
        )

        logging_gateway.error.assert_any_call("Malformed WhatsApp message payload.")
        messaging_service.handle_text_message.assert_not_awaited()

    async def test_process_message_event_new_user_profile_fallback_paths(self) -> None:
        messaging_service = _make_messaging_service()
        user_service = _make_user_service(known_users={})
        ext = _new_extension(
            config=_make_config(beta_active=False),
            relational_storage_gateway=_MemoryRelational(),
            messaging_service=messaging_service,
            user_service=user_service,
        )

        await ext._process_message_event(  # pylint: disable=protected-access
            {"contacts": [{"wa_id": "15550120"}]},
            {
                "id": "wamid-profile-fallback-1",
                "from": "15550120",
                "type": "text",
                "text": {"body": "hello"},
            },
        )
        user_service.add_known_user.assert_awaited_with(
            "15550120",
            "15550120",
            "15550120",
        )

        await ext._process_message_event(  # pylint: disable=protected-access
            {
                "contacts": [
                    {
                        "wa_id": "15550121",
                        "profile": {"name": 123},
                    }
                ]
            },
            {
                "id": "wamid-profile-fallback-2",
                "from": "15550121",
                "type": "text",
                "text": {"body": "hello"},
            },
        )
        user_service.add_known_user.assert_awaited_with(
            "15550121",
            "15550121",
            "15550121",
        )

        await ext._process_message_event(  # pylint: disable=protected-access
            {"contacts": ["bad-contact"]},
            {
                "id": "wamid-profile-fallback-3",
                "from": "15550122",
                "type": "text",
                "text": {"body": "hello"},
            },
        )
        user_service.add_known_user.assert_awaited_with(
            "15550122",
            "15550122",
            "15550122",
        )

    async def test_process_message_event_catches_key_error(self) -> None:
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            relational_storage_gateway=_MemoryRelational(),
            logging_gateway=logging_gateway,
            user_service=_make_user_service(known_users={"15550130": "known"}),
        )

        await ext._process_message_event(  # pylint: disable=protected-access
            {"contacts": [{"wa_id": "15550130", "profile": {"name": "Known"}}]},
            {
                "id": "wamid-key-error",
                "from": "15550130",
            },
        )

        logging_gateway.error.assert_any_call("Malformed WhatsApp message payload.")

    async def test_wacapi_event_non_list_entries_is_malformed(self) -> None:
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            logging_gateway=logging_gateway,
        )
        payload = _make_request({"entry": "bad"})

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        logging_gateway.error.assert_any_call("Malformed WhatsApp event payload.")

    async def test_wacapi_event_skips_invalid_entry_change_and_value_items(
        self,
    ) -> None:
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            logging_gateway=logging_gateway,
        )
        payload = _make_request(
            {
                "entry": [
                    "bad-entry",
                    {"changes": "bad-changes"},
                    {
                        "changes": [
                            "bad-change",
                            {"value": "bad-value"},
                            {"value": {}},
                        ]
                    },
                ]
            }
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        logging_gateway.error.assert_not_called()

    async def test_wacapi_event_skips_routes_without_client_profile_id(self) -> None:
        ext = _new_extension(config=_make_config(beta_active=False))
        ext._resolve_ingress_route = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            return_value={"tenant_id": "tenant-a"}
        )
        ext._process_message_event = AsyncMock()  # type: ignore[method-assign]  # pylint: disable=protected-access
        payload = _make_request(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "metadata": {"phone_number_id": "pnid-1"},
                                    "messages": [{"id": "wamid-1", "from": "15550001"}],
                                }
                            }
                        ]
                    }
                ]
            }
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        ext._process_message_event.assert_not_awaited()

    async def test_wacapi_event_logs_malformed_status_item_and_continues(self) -> None:
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            logging_gateway=logging_gateway,
        )
        payload = _make_request(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "statuses": [
                                        "bad-status",
                                        {"id": "st-good", "status": "sent"},
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
        )

        with patch.object(
            ext, "_process_status_event", new=AsyncMock()
        ) as process_status:
            await ext._wacapi_event(payload)  # pylint: disable=protected-access

        logging_gateway.error.assert_any_call("Malformed WhatsApp status payload.")
        process_status.assert_awaited_once_with({"id": "st-good", "status": "sent"})

    async def test_event_with_no_messages_or_statuses_still_acknowledges(self) -> None:
        ext = _new_extension(config=_make_config(beta_active=False))
        payload = _make_request(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {},
                            }
                        ]
                    }
                ]
            }
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

    async def test_unknown_message_type_delegates_to_message_handlers(self) -> None:
        ext = _new_extension(config=_make_config(beta_active=False))
        payload = _make_request(
            _make_message_event(
                {
                    "id": "wamid-unknown",
                    "type": "unknown",
                    "unknown": {"value": "x"},
                },
                sender="15550010",
            )
        )

        with patch.object(
            ext, "_call_message_handlers", new=AsyncMock()
        ) as route_handlers:
            await ext._wacapi_event(payload)  # pylint: disable=protected-access

        route_handlers.assert_awaited_once_with(
            message={
                "id": "wamid-unknown",
                "type": "unknown",
                "unknown": {"value": "x"},
            },
            message_type="unknown",
            sender="15550010",
        )

    async def test_allowed_user_continues_processing(self) -> None:
        client = _make_client()
        client.user_access_policy.return_value = MessagingClientUserAccessPolicy(
            mode="allow-only",
            users=("15550011",),
            denied_message="Not enabled",
        )
        messaging_service = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(
                beta_active=False,
                access_mode="allow-only",
                access_users=["15550011"],
                denied_message="Not enabled",
            ),
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"15550011": "known"}),
        )
        payload = _make_request(
            _make_message_event(
                {
                    "id": "wamid-allow",
                    "type": "text",
                    "text": {"body": "hello"},
                },
                sender="15550011",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        messaging_service.handle_text_message.assert_awaited_once_with(
            "whatsapp",
            room_id="15550011",
            sender="15550011",
            message="hello",
            message_context=ANY,
            ingress_metadata=ANY,
            message_id="wamid-allow",
        )
        client.send_text_message.assert_not_awaited()

    async def test_response_upload_error_paths_are_logged(self) -> None:
        client = _make_client()
        client.upload_media = AsyncMock(
            side_effect=[
                _error_payload("audio-upload-failed", status=500),
                _error_payload("file-upload-failed", status=500),
                _error_payload("image-upload-failed", status=500),
                _error_payload("video-upload-failed", status=500),
            ]
        )
        client.send_text_message = AsyncMock(
            return_value=_error_payload("text-failed", status=500)
        )
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(
            return_value=[
                {"type": "audio", "file": {"uri": "/tmp/a.ogg", "type": "audio/ogg"}},
                {
                    "type": "file",
                    "file": {
                        "uri": "/tmp/f.pdf",
                        "type": "application/pdf",
                        "name": "f.pdf",
                    },
                },
                {"type": "image", "file": {"uri": "/tmp/i.png", "type": "image/png"}},
                {"type": "text", "content": "reply"},
                {"type": "video", "file": {"uri": "/tmp/v.mp4", "type": "video/mp4"}},
            ]
        )
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"15550012": "known"}),
            logging_gateway=logging_gateway,
        )
        payload = _make_request(
            _make_message_event(
                {
                    "id": "wamid-upload-error",
                    "type": "text",
                    "text": {"body": "incoming"},
                },
                sender="15550012",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        client.send_audio_message.assert_not_awaited()
        client.send_document_message.assert_not_awaited()
        client.send_image_message.assert_not_awaited()
        client.send_video_message.assert_not_awaited()
        logging_gateway.error.assert_any_call("audio upload failed.")
        logging_gateway.error.assert_any_call("audio-upload-failed")
        logging_gateway.error.assert_any_call("document upload failed.")
        logging_gateway.error.assert_any_call("file-upload-failed")
        logging_gateway.error.assert_any_call("image upload failed.")
        logging_gateway.error.assert_any_call("image-upload-failed")
        logging_gateway.error.assert_any_call("text send failed.")
        logging_gateway.error.assert_any_call("text-failed")
        logging_gateway.error.assert_any_call("video upload failed.")
        logging_gateway.error.assert_any_call("video-upload-failed")

    async def test_response_upload_none_payload_skips_send_calls(self) -> None:
        client = _make_client()
        client.upload_media = AsyncMock(side_effect=[None, None, None, None])
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(
            return_value=[
                {"type": "audio", "file": {"uri": "/tmp/a.ogg", "type": "audio/ogg"}},
                {
                    "type": "file",
                    "file": {
                        "uri": "/tmp/f.pdf",
                        "type": "application/pdf",
                        "name": "f.pdf",
                    },
                },
                {"type": "image", "file": {"uri": "/tmp/i.png", "type": "image/png"}},
                {"type": "video", "file": {"uri": "/tmp/v.mp4", "type": "video/mp4"}},
            ]
        )
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"15550014": "known"}),
        )
        payload = _make_request(
            _make_message_event(
                {
                    "id": "wamid-upload-none",
                    "type": "text",
                    "text": {"body": "incoming"},
                },
                sender="15550014",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        client.send_audio_message.assert_not_awaited()
        client.send_document_message.assert_not_awaited()
        client.send_image_message.assert_not_awaited()
        client.send_video_message.assert_not_awaited()

    async def test_response_upload_without_id_or_error_skips_send_calls(self) -> None:
        client = _make_client()
        client.upload_media = AsyncMock(
            side_effect=[
                _ok_payload({}),
                _ok_payload({}),
                _ok_payload({}),
                _ok_payload({}),
            ]
        )
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(
            return_value=[
                {"type": "audio", "file": {"uri": "/tmp/a.ogg", "type": "audio/ogg"}},
                {
                    "type": "file",
                    "file": {
                        "uri": "/tmp/f.pdf",
                        "type": "application/pdf",
                        "name": "f.pdf",
                    },
                },
                {"type": "image", "file": {"uri": "/tmp/i.png", "type": "image/png"}},
                {"type": "video", "file": {"uri": "/tmp/v.mp4", "type": "video/mp4"}},
            ]
        )
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"15550015": "known"}),
        )
        payload = _make_request(
            _make_message_event(
                {
                    "id": "wamid-upload-empty",
                    "type": "text",
                    "text": {"body": "incoming"},
                },
                sender="15550015",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        client.send_audio_message.assert_not_awaited()
        client.send_document_message.assert_not_awaited()
        client.send_image_message.assert_not_awaited()
        client.send_video_message.assert_not_awaited()

    async def test_response_send_error_paths_are_logged(self) -> None:
        client = _make_client()
        client.upload_media = AsyncMock(
            side_effect=[
                _ok_payload({"id": "audio-id"}),
                _ok_payload({"id": "file-id"}),
                _ok_payload({"id": "image-id"}),
                _ok_payload({"id": "video-id"}),
            ]
        )
        client.send_audio_message = AsyncMock(
            return_value=_error_payload("audio-send", status=500)
        )
        client.send_document_message = AsyncMock(
            return_value=_error_payload("file-send", status=500)
        )
        client.send_image_message = AsyncMock(
            return_value=_error_payload("image-send", status=500)
        )
        client.send_video_message = AsyncMock(
            return_value=_error_payload("video-send", status=500)
        )
        client.send_text_message = AsyncMock(return_value=_ok_payload({"messages": []}))
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(
            return_value=[
                {"type": "audio", "file": {"uri": "/tmp/a.ogg", "type": "audio/ogg"}},
                {
                    "type": "file",
                    "file": {
                        "uri": "/tmp/f.pdf",
                        "type": "application/pdf",
                        "name": "f.pdf",
                    },
                },
                {"type": "image", "file": {"uri": "/tmp/i.png", "type": "image/png"}},
                {"type": "text", "content": "reply"},
                {"type": "video", "file": {"uri": "/tmp/v.mp4", "type": "video/mp4"}},
            ]
        )
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"15550013": "known"}),
            logging_gateway=logging_gateway,
        )
        payload = _make_request(
            _make_message_event(
                {
                    "id": "wamid-send-error",
                    "type": "text",
                    "text": {"body": "incoming"},
                },
                sender="15550013",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        logging_gateway.error.assert_any_call("audio send failed.")
        logging_gateway.error.assert_any_call("audio-send")
        logging_gateway.error.assert_any_call("document send failed.")
        logging_gateway.error.assert_any_call("file-send")
        logging_gateway.error.assert_any_call("image send failed.")
        logging_gateway.error.assert_any_call("image-send")
        logging_gateway.error.assert_any_call("video send failed.")
        logging_gateway.error.assert_any_call("video-send")

    async def test_malformed_event_payload_is_logged_and_acknowledged(self) -> None:
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            logging_gateway=logging_gateway,
        )
        payload = _make_request({"entry": []})

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        logging_gateway.error.assert_any_call("Malformed WhatsApp event payload.")

    async def test_malformed_event_request_still_returns(self) -> None:
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            logging_gateway=logging_gateway,
        )

        await ext._wacapi_event(_make_request({"entry": []}))  # pylint: disable=protected-access

        logging_gateway.error.assert_any_call("Malformed WhatsApp event payload.")

    async def test_call_message_handlers_supported_and_unsupported_paths(self) -> None:
        client = _make_client()
        messaging_service = _make_messaging_service()
        supported = _MhExtension(supported=True, message_types=["custom"])
        unsupported = _MhExtension(supported=False, message_types=["custom"])
        wrong_type = _MhExtension(supported=True, message_types=["text"])
        messaging_service.mh_extensions = [supported, unsupported, wrong_type]
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            messaging_service=messaging_service,
            logging_gateway=logging_gateway,
        )

        def _create_task(coro):
            coro.close()
            return "task"

        with (
            patch(
                "mugen.core.plugin.whatsapp.wacapi.ipc_ext.asyncio.create_task",
                side_effect=_create_task,
            ) as create_task,
            patch(
                "mugen.core.plugin.whatsapp.wacapi.ipc_ext.asyncio.gather",
                new=AsyncMock(return_value=None),
            ) as gather,
        ):
            await ext._call_message_handlers(  # pylint: disable=protected-access
                message={"id": "m1"},
                message_type="custom",
                sender="15550005",
            )

        supported.handle_message.assert_called_once()
        kwargs = supported.handle_message.call_args.kwargs
        self.assertEqual(
            kwargs,
            {
                "platform": "whatsapp",
                "room_id": "15550005",
                "sender": "15550005",
                "message": {"id": "m1"},
                "message_context": None,
                "ingress_metadata": {
                    "ingress_route": {
                        "tenant_id": "00000000-0000-0000-0000-000000000000",
                        "tenant_slug": "global",
                        "platform": "whatsapp",
                        "channel_key": "whatsapp",
                        "identifier_claims": {},
                        "channel_profile_id": None,
                        "client_profile_id": None,
                        "service_route_key": None,
                        "route_key": None,
                        "binding_id": None,
                        "client_profile_key": None,
                        "tenant_resolution": {
                            "mode": "fallback_global",
                            "reason_code": "no_ingress_route",
                            "source": "whatsapp.ipc_extension",
                        },
                    },
                    "tenant_resolution": {
                        "mode": "fallback_global",
                        "reason_code": "no_ingress_route",
                        "source": "whatsapp.ipc_extension",
                    },
                },
                "scope": kwargs["scope"],
            },
        )
        self.assertEqual(kwargs["scope"].tenant_id, "00000000-0000-0000-0000-000000000000")
        self.assertEqual(kwargs["scope"].platform, "whatsapp")
        self.assertEqual(kwargs["scope"].channel_id, "whatsapp")
        self.assertEqual(kwargs["scope"].room_id, "15550005")
        self.assertEqual(kwargs["scope"].sender_id, "15550005")
        self.assertEqual(kwargs["scope"].conversation_id, "15550005")
        create_task.assert_called_once()
        gather.assert_called_once_with("task")

        messaging_service.mh_extensions = []
        await ext._call_message_handlers(  # pylint: disable=protected-access
            message={"id": "m2"},
            message_type="unknown",
            sender="15550006",
        )
        logging_gateway.debug.assert_any_call("Unsupported message type: unknown.")
        client.send_text_message.assert_awaited_with(
            message="Unsupported message type..",
            recipient="15550006",
            reply_to="m2",
        )

        client.send_text_message.reset_mock()
        await ext._call_message_handlers(  # pylint: disable=protected-access
            message={"id": "m3"},
            message_type="unknown",
            sender=None,
        )
        client.send_text_message.assert_not_awaited()

    async def test_call_message_handlers_uses_message_context_route_and_active_route(
        self,
    ) -> None:
        messaging_service = _make_messaging_service()
        supported = _MhExtension(supported=True, message_types=["custom"])
        messaging_service.mh_extensions = [supported]
        ext = _new_extension(
            config=_make_config(beta_active=False),
            messaging_service=messaging_service,
            logging_gateway=Mock(),
        )

        def _create_task(coro):
            coro.close()
            return "task"

        with (
            patch(
                "mugen.core.plugin.whatsapp.wacapi.ipc_ext.asyncio.create_task",
                side_effect=_create_task,
            ),
            patch(
                "mugen.core.plugin.whatsapp.wacapi.ipc_ext.asyncio.gather",
                new=AsyncMock(return_value=None),
            ),
        ):
            await ext._call_message_handlers(  # pylint: disable=protected-access
                message={"id": "m4"},
                message_type="custom",
                sender="15550007",
                message_context=[
                    {"type": "seed", "content": "ctx"},
                    {"type": "ingress_route", "content": {"tenant_id": "tenant-1"}},
                ],
            )

            ext._active_ingress_route = {"tenant_id": "tenant-2"}  # pylint: disable=protected-access
            await ext._call_message_handlers(  # pylint: disable=protected-access
                message={"id": "m5"},
                message_type="custom",
                sender="15550008",
                message_context=[
                    {"type": "seed", "content": "ctx"},
                    {"type": "ingress_route", "content": "bad"},
                ],
            )

        first_call = supported.handle_message.call_args_list[0].kwargs
        second_call = supported.handle_message.call_args_list[1].kwargs
        self.assertEqual(
            first_call["ingress_metadata"]["ingress_route"]["tenant_id"],
            "tenant-1",
        )
        self.assertEqual(
            second_call["ingress_metadata"]["ingress_route"]["tenant_id"],
            "tenant-2",
        )

    async def test_ingress_router_default_and_helper_fallback_branches(self) -> None:
        ext = WhatsAppWACAPIIPCExtension(
            config=_make_config(beta_active=False),
            logging_gateway=Mock(),
            relational_storage_gateway=_MemoryRelational(),
            messaging_service=_make_messaging_service(),
            user_service=_make_user_service(),
            whatsapp_client=_make_client(),
            ingress_routing_service=None,
        )
        sentinel_router = object()
        with patch.object(
            ipc_ext,
            "DefaultIngressRoutingService",
            return_value=sentinel_router,
        ) as router_ctor:
            self.assertIs(ext._ingress_router(), sentinel_router)  # pylint: disable=protected-access
            self.assertIs(ext._ingress_router(), sentinel_router)  # pylint: disable=protected-access
            router_ctor.assert_called_once()

        self.assertIsNone(ext._coerce_nonempty_string(123))  # pylint: disable=protected-access
        self.assertEqual(  # pylint: disable=protected-access
            ext._compose_message_context(
                ingress_route={"tenant_slug": "tenant-a"},
                extra_context=["bad"],
            ),
            [
                {
                    "type": "ingress_route",
                    "content": {"tenant_slug": "tenant-a"},
                }
            ],
        )
        merged = ext._merge_ingress_metadata(  # pylint: disable=protected-access
            payload={"metadata": {"k": "v"}},
            ingress_route={"tenant_slug": "tenant-a"},
        )
        self.assertEqual(merged["metadata"]["k"], "v")
        self.assertEqual(merged["metadata"]["ingress_route"]["tenant_slug"], "tenant-a")
        self.assertEqual(  # pylint: disable=protected-access
            ext._extract_phone_number_id({"metadata": {"phone_number_id": " 999 "}}),
            "999",
        )
        self.assertEqual(  # pylint: disable=protected-access
            ext._extract_phone_number_id({"metadata": {"phone_number_id": "   "}}),
            "pnid-1",
        )

    async def test_missing_binding_ingress_route_is_dead_lettered_and_dropped(self) -> None:
        class _FallbackRouter:
            async def resolve(self, request):  # noqa: ARG002
                return IngressRouteResolution(
                    ok=False,
                    reason_code=IngressRouteReason.MISSING_BINDING.value,
                    reason_detail=None,
                )

        logger = Mock()
        relational = _MemoryRelational()
        messaging = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            logging_gateway=logger,
            relational_storage_gateway=relational,
            messaging_service=messaging,
            ingress_routing_service=_FallbackRouter(),
        )
        payload = _make_request(
            _make_message_event(
                {
                    "id": "wamid-unresolved",
                    "type": "text",
                    "text": {"body": "hello"},
                },
                sender="15550014",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access
        messaging.handle_text_message.assert_not_awaited()
        self.assertEqual(
            ext._metrics.get("whatsapp.ipc.route.unresolved"),  # pylint: disable=protected-access
            1,
        )
        self.assertEqual(len(relational.dead_letters), 1)
        self.assertEqual(relational.dead_letters[0]["reason_code"], "route_unresolved")
        self.assertEqual(relational.dead_letters[0]["error_message"], "missing_binding")
        logger.warning.assert_any_call(
            "Dropped WhatsApp ingress due to unresolved route "
            "reason_code=missing_binding phone_number_id='pnid-1'."
        )

        class _UnresolvedWithDetailRouter:
            async def resolve(self, request):  # noqa: ARG002
                return IngressRouteResolution(
                    ok=False,
                    reason_code=IngressRouteReason.RESOLUTION_ERROR.value,
                    reason_detail="detail",
                )

        ext_with_detail = _new_extension(
            config=_make_config(beta_active=False),
            logging_gateway=Mock(),
            relational_storage_gateway=_MemoryRelational(),
            ingress_routing_service=_UnresolvedWithDetailRouter(),
        )
        await ext_with_detail._resolve_ingress_route(  # pylint: disable=protected-access
            phone_number_id="pnid-1",
            webhook_payload={"entry": []},
        )
        self.assertIn(
            "detail",
            str(ext_with_detail._relational_storage_gateway.dead_letters[0]["error_message"]),  # pylint: disable=protected-access
        )

    async def test_event_skips_processing_when_ingress_route_resolution_returns_none(
        self,
    ) -> None:
        messaging = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            messaging_service=messaging,
        )
        ext._resolve_ingress_route = AsyncMock(return_value=None)  # type: ignore[method-assign]  # pylint: disable=protected-access

        await ext._wacapi_event(  # pylint: disable=protected-access
            _make_request(
                _make_message_event(
                    {
                        "id": "wamid-skip",
                        "type": "text",
                        "text": {"body": "hello"},
                    },
                    sender="15550015",
                )
            )
        )

        messaging.handle_text_message.assert_not_awaited()

    async def test_process_message_and_status_normalize_explicit_ingress_route(self) -> None:
        ext = _new_extension(config=_make_config(beta_active=False))
        with (
            patch.object(ext, "_is_duplicate_event", new=AsyncMock(return_value=True)),
            patch.object(ext, "_emit_processing_signal", new=AsyncMock()),
        ):
            await ext._process_message_event(  # pylint: disable=protected-access
                event_value={},
                message={"id": "m-route", "type": "text", "from": "15550015"},
                ingress_route={"tenant_slug": "tenant-a"},
            )
            await ext._process_status_event(  # pylint: disable=protected-access
                {"id": "s-route", "status": "sent", "recipient_id": "15550015"},
                ingress_route={"tenant_slug": "tenant-a"},
            )


def _ok_payload(data: dict | None = None, raw: str = "{}") -> dict:
    return {
        "ok": True,
        "status": 200,
        "data": {} if data is None else data,
        "error": None,
        "raw": raw,
    }


def _error_payload(
    error: str = "error",
    *,
    status: int = 500,
    raw: str = '{"error":"error"}',
) -> dict:
    return {
        "ok": False,
        "status": status,
        "data": None,
        "error": error,
        "raw": raw,
    }

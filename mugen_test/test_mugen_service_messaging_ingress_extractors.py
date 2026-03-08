"""Unit tests for shared messaging ingress extractors."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from mugen.core.service import messaging_ingress_extractors as extractors
from mugen.core.service.context_scope_resolution import ContextScopeResolutionError
from mugen.core.utility import signal_ingress as signal_ingress_mod
from mugen.core.utility.client_profile_runtime import (
    client_profile_scope,
    client_profile_id_from_ingress_route,
    get_active_client_profile_id,
    normalize_client_profile_id,
)

_CLIENT_PROFILE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _signal_config() -> SimpleNamespace:
    return SimpleNamespace(
        signal=SimpleNamespace(
            account=SimpleNamespace(number="+15550000001"),
        )
    )


class TestMugenServiceMessagingIngressExtractors(unittest.IsolatedAsyncioTestCase):
    """Covers normalization helpers and platform extractor branches."""

    async def test_resolve_ingress_route_handles_none_success_and_fail_closed(self) -> None:
        logger = Mock()

        self.assertIsNone(
            await extractors._resolve_ingress_route(  # pylint: disable=protected-access
                platform="line",
                channel_key="line",
                identifier_type="path_token",
                identifier_value=None,
                claims={},
                relational_storage_gateway=object(),
                logging_gateway=logger,
            )
        )

        router = SimpleNamespace(
            resolve=AsyncMock(return_value=SimpleNamespace(ok=True)),
        )
        with (
            patch.object(
                extractors,
                "DefaultIngressRoutingService",
                return_value=router,
            ),
            patch.object(
                extractors,
                "resolve_ingress_route_context",
                return_value={"client_profile_id": str(_CLIENT_PROFILE_ID)},
            ) as resolve_context,
        ):
            route = await extractors._resolve_ingress_route(  # pylint: disable=protected-access
                platform="line",
                channel_key="line",
                identifier_type="path_token",
                identifier_value="token-1",
                claims={"path_token": "token-1"},
                relational_storage_gateway=object(),
                logging_gateway=logger,
            )

        self.assertEqual(route, {"client_profile_id": str(_CLIENT_PROFILE_ID)})
        resolve_context.assert_called_once()

        with (
            patch.object(
                extractors,
                "DefaultIngressRoutingService",
                return_value=router,
            ),
            patch.object(
                extractors,
                "resolve_ingress_route_context",
                side_effect=ContextScopeResolutionError(
                    reason_code="missing_binding",
                    detail="no route",
                ),
            ),
        ):
            route = await extractors._resolve_ingress_route(  # pylint: disable=protected-access
                platform="line",
                channel_key="line",
                identifier_type="path_token",
                identifier_value="token-1",
                claims={"path_token": "token-1"},
                relational_storage_gateway=object(),
                logging_gateway=logger,
            )

        self.assertIsNone(route)
        logger.warning.assert_called_once()

    async def test_line_extractor_covers_event_variants_and_defaults(self) -> None:
        self.assertEqual(
            await extractors.extract_line_stage_entries(
                path_token="path-1",
                payload={},
                relational_storage_gateway=object(),
                logging_gateway=Mock(),
            ),
            [],
        )

        with patch.object(
            extractors,
            "_resolve_ingress_route",
            new=AsyncMock(
                return_value={
                    "client_profile_id": str(_CLIENT_PROFILE_ID),
                    "client_profile_key": "line-a",
                }
            ),
        ):
            entries = await extractors.extract_line_stage_entries(
                path_token="path-1",
                payload={
                    "events": [
                        "skip",
                        {
                            "type": "message",
                            "source": {"userId": "U-1"},
                            "message": {"id": "m-1"},
                        },
                        {
                            "type": "postback",
                            "source": {"userId": "U-2"},
                            "postback": {"data": "payload"},
                        },
                    ]
                },
                relational_storage_gateway=object(),
                logging_gateway=Mock(),
            )

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].event.client_profile_id, _CLIENT_PROFILE_ID)
        self.assertEqual(entries[0].event.event_id, "m-1")
        self.assertEqual(entries[0].event.sender, "U-1")
        self.assertEqual(entries[0].event.room_id, "U-1")
        self.assertEqual(
            entries[0].event.provider_context["client_profile_key"],
            "line-a",
        )
        self.assertEqual(entries[1].event.event_type, "postback")
        self.assertTrue(entries[1].event.dedupe_key.startswith("postback:"))

        logger = Mock()
        with patch.object(
            extractors,
            "_resolve_ingress_route",
            new=AsyncMock(return_value={}),
        ):
            self.assertEqual(
                await extractors.extract_line_stage_entries(
                    path_token="path-1",
                    payload={"events": [{"type": "message"}]},
                    relational_storage_gateway=object(),
                    logging_gateway=logger,
                ),
                [],
            )
        logger.warning.assert_called_once()

    async def test_telegram_extractor_covers_message_and_callback_query(self) -> None:
        with patch.object(
            extractors,
            "_resolve_ingress_route",
            new=AsyncMock(
                return_value={
                    "client_profile_id": str(_CLIENT_PROFILE_ID),
                    "client_profile_key": "telegram-a",
                }
            ),
        ):
            entries = await extractors.extract_telegram_stage_entries(
                path_token="telegram-path",
                payload={
                    "update_id": 42,
                    "message": {
                        "chat": {"id": 111},
                        "from": {"id": 222},
                        "text": "hello",
                    },
                    "callback_query": {
                        "id": "cb-1",
                        "from": {"id": 333},
                        "message": {"chat": {"id": 444}},
                    },
                },
                relational_storage_gateway=object(),
                logging_gateway=Mock(),
            )

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].event.client_profile_id, _CLIENT_PROFILE_ID)
        self.assertEqual(entries[0].event.room_id, "111")
        self.assertEqual(entries[0].event.sender, "222")
        self.assertEqual(entries[1].event.event_type, "callback_query")
        self.assertEqual(entries[1].event.event_id, "cb-1")
        self.assertEqual(entries[1].event.room_id, "444")
        self.assertEqual(entries[1].event.sender, "333")

    async def test_wechat_extractor_covers_provider_context(self) -> None:
        with patch.object(
            extractors,
            "_resolve_ingress_route",
            new=AsyncMock(
                return_value={
                    "client_profile_id": str(_CLIENT_PROFILE_ID),
                    "client_profile_key": "wechat-a",
                }
            ),
        ):
            entries = await extractors.extract_wechat_stage_entries(
                path_token="wechat-path",
                provider="official_account",
                payload={
                    "FromUserName": "wechat-user",
                    "MsgId": "msg-1",
                    "MsgType": "text",
                },
                relational_storage_gateway=object(),
                logging_gateway=Mock(),
            )

        self.assertEqual(len(entries), 1)
        event = entries[0].event
        self.assertEqual(event.client_profile_id, _CLIENT_PROFILE_ID)
        self.assertEqual(event.event_type, "official_account:event")
        self.assertEqual(event.room_id, "wechat-user")
        self.assertEqual(event.provider_context["provider"], "official_account")
        self.assertEqual(event.provider_context["client_profile_key"], "wechat-a")

        logger = Mock()
        with patch.object(
            extractors,
            "_resolve_ingress_route",
            new=AsyncMock(return_value={}),
        ):
            self.assertEqual(
                await extractors.extract_wechat_stage_entries(
                    path_token="wechat-path",
                    provider="official_account",
                    payload={"FromUserName": "wechat-user"},
                    relational_storage_gateway=object(),
                    logging_gateway=logger,
                ),
                [],
            )
        logger.warning.assert_called_once()

    async def test_whatsapp_extractor_covers_skips_messages_and_statuses(self) -> None:
        self.assertEqual(
            await extractors.extract_whatsapp_stage_entries(
                path_token="whatsapp-path",
                payload={},
                relational_storage_gateway=object(),
                logging_gateway=Mock(),
            ),
            [],
        )

        route_results = [
            {
                "client_profile_id": str(_CLIENT_PROFILE_ID),
                "client_profile_key": "wa-a",
            },
            {
                "client_profile_id": str(_CLIENT_PROFILE_ID),
                "client_profile_key": "wa-a",
            },
        ]

        async def _resolve_route(**_kwargs):
            return route_results.pop(0)

        with patch.object(
            extractors,
            "_resolve_ingress_route",
            new=AsyncMock(side_effect=_resolve_route),
        ):
            entries = await extractors.extract_whatsapp_stage_entries(
                path_token="whatsapp-path",
                payload={
                    "entry": [
                        "skip",
                        {
                            "changes": [
                                "skip",
                                {
                                    "value": {
                                        "metadata": {"phone_number_id": "phone-1"},
                                        "contacts": [{"wa_id": "contact-wa"}],
                                        "messages": [
                                            "skip",
                                            {
                                                "id": "wamid-1",
                                            },
                                        ],
                                    }
                                },
                                {
                                    "value": {
                                        "metadata": {"phone_number_id": "phone-2"},
                                        "statuses": [
                                            "skip",
                                            {
                                                "id": "status-1",
                                                "recipient_id": "recipient-1",
                                            }
                                        ],
                                    }
                                },
                            ]
                        },
                    ]
                },
                relational_storage_gateway=object(),
                logging_gateway=Mock(),
            )

        self.assertEqual(len(entries), 2)
        message_event = entries[0].event
        self.assertEqual(message_event.client_profile_id, _CLIENT_PROFILE_ID)
        self.assertEqual(message_event.sender, "contact-wa")
        self.assertEqual(message_event.room_id, "contact-wa")
        self.assertEqual(message_event.identifier_value, "phone-1")
        self.assertEqual(message_event.provider_context["path_token"], "whatsapp-path")
        status_event = entries[1].event
        self.assertEqual(status_event.client_profile_id, _CLIENT_PROFILE_ID)
        self.assertEqual(status_event.event_type, "status")
        self.assertEqual(status_event.identifier_value, "phone-2")
        self.assertEqual(status_event.sender, "recipient-1")
        self.assertEqual(status_event.room_id, "recipient-1")
        self.assertEqual(status_event.provider_context["path_token"], "whatsapp-path")

        with patch.object(
            extractors,
            "_resolve_ingress_route",
            new=AsyncMock(return_value={"client_profile_id": str(_CLIENT_PROFILE_ID)}),
        ):
            entries = await extractors.extract_whatsapp_stage_entries(
                path_token="whatsapp-path",
                payload={
                    "entry": [
                        {
                            "changes": [
                                {
                                    "value": {
                                        "metadata": {"phone_number_id": "phone-3"},
                                        "contacts": ["skip", {"wa_id": "contact-3"}],
                                        "messages": [{"id": "wamid-3"}],
                                    }
                                }
                            ]
                        }
                    ]
                },
                relational_storage_gateway=object(),
                logging_gateway=Mock(),
            )
        self.assertEqual(entries[0].event.sender, "contact-3")

        with patch.object(
            extractors,
            "_resolve_ingress_route",
            new=AsyncMock(return_value={"client_profile_id": str(_CLIENT_PROFILE_ID)}),
        ):
            entries = await extractors.extract_whatsapp_stage_entries(
                path_token="whatsapp-path",
                payload={
                    "entry": [
                        {
                            "changes": [
                                {
                                    "value": {
                                        "metadata": {"phone_number_id": "phone-4"},
                                        "contacts": [
                                            {"profile": {"name": "skip-me"}},
                                            {"wa_id": "contact-4"},
                                        ],
                                        "messages": [{"id": "wamid-4"}],
                                    }
                                }
                            ]
                        }
                    ]
                },
                relational_storage_gateway=object(),
                logging_gateway=Mock(),
            )
        self.assertEqual(entries[0].event.sender, "contact-4")

    async def test_whatsapp_extractor_preserves_sender_and_handles_empty_contacts(
        self,
    ) -> None:
        with patch.object(
            extractors,
            "_resolve_ingress_route",
            new=AsyncMock(return_value={"client_profile_id": str(_CLIENT_PROFILE_ID)}),
        ):
            entries = await extractors.extract_whatsapp_stage_entries(
                path_token="whatsapp-path",
                payload={
                    "entry": [
                        {
                            "changes": [
                                {
                                    "value": {
                                        "metadata": {"phone_number_id": "phone-1"},
                                        "messages": [
                                            {
                                                "id": "wamid-sender",
                                                "from": "sender-1",
                                            },
                                            {
                                                "id": "wamid-empty-contacts",
                                            },
                                        ],
                                        "contacts": [],
                                    }
                                }
                            ]
                        }
                    ]
                },
                relational_storage_gateway=object(),
                logging_gateway=Mock(),
            )

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].event.sender, "sender-1")
        self.assertEqual(entries[0].event.room_id, "sender-1")
        self.assertIsNone(entries[1].event.sender)
        self.assertIsNone(entries[1].event.room_id)

    async def test_signal_helper_paths_and_signal_extractor(self) -> None:
        self.assertIsNone(extractors._nonempty_text(1))  # pylint: disable=protected-access
        self.assertEqual(
            extractors._nonempty_text(" hi "),  # pylint: disable=protected-access
            "hi",
        )
        self.assertEqual(
            extractors._dedupe_key("message", " evt-1 ", {"a": 1}),  # pylint: disable=protected-access
            "message:evt-1",
        )
        self.assertTrue(
            extractors._dedupe_key("message", None, {"a": 1}).startswith("message:")
        )  # pylint: disable=protected-access

        self.assertIsNone(signal_ingress_mod.signal_envelope({"params": []}))
        envelope = {
            "sourceNumber": "+15550001",
            "timestamp": 123,
            "dataMessage": {"message": "hello"},
        }
        self.assertEqual(
            signal_ingress_mod.signal_envelope({"params": {"envelope": envelope}}),
            envelope,
        )
        self.assertEqual(
            signal_ingress_mod.signal_sender({"sourceUuid": "uuid-1"}),
            "uuid-1",
        )
        self.assertIsNone(
            signal_ingress_mod.signal_event_id({"timestamp": True})
        )
        self.assertIsNone(
            signal_ingress_mod.signal_event_id({"timestamp": "bad"})
        )
        self.assertEqual(
            signal_ingress_mod.signal_event_id({"timestamp": 5}),
            "5",
        )
        self.assertEqual(
            signal_ingress_mod.signal_event_id(
                {"timestamp": 6, "source": "+15550002"}
            ),
            "+15550002:6",
        )
        self.assertEqual(
            signal_ingress_mod.signal_event_type({"receiptMessage": {}}),
            "receipt",
        )
        self.assertEqual(
            signal_ingress_mod.signal_event_type({"typingMessage": {}}),
            "typing",
        )
        self.assertEqual(
            signal_ingress_mod.signal_event_type({"other": True}),
            "event",
        )
        self.assertEqual(
            signal_ingress_mod.signal_event_type({"dataMessage": {"reaction": {}}}),
            "reaction",
        )

        self.assertEqual(
            client_profile_id_from_ingress_route(
                {"client_profile_id": str(_CLIENT_PROFILE_ID)}
            ),
            _CLIENT_PROFILE_ID,
        )
        self.assertIsNone(client_profile_id_from_ingress_route(None))

        self.assertEqual(
            extractors.extract_signal_stage_entries(  # pylint: disable=protected-access
                config=_signal_config(),
                payload={"params": {}},
            ),
            [],
        )

        entries = extractors.extract_signal_stage_entries(
            config=_signal_config(),
            payload={
                "client_profile_id": str(_CLIENT_PROFILE_ID),
                "params": {
                    "envelope": {
                        "sourceNumber": "+15550001",
                        "timestamp": 123,
                        "dataMessage": {"reaction": {"emoji": "👍"}},
                    }
                },
            },
        )
        self.assertEqual(len(entries), 1)
        event = entries[0].event
        self.assertEqual(event.client_profile_id, _CLIENT_PROFILE_ID)
        self.assertEqual(event.event_type, "reaction")
        self.assertEqual(event.event_id, "+15550001:123")
        self.assertEqual(event.identifier_value, "+15550000001")
        self.assertEqual(event.room_id, "+15550001")
        self.assertEqual(event.sender, "+15550001")
        self.assertEqual(event.provider_context["account_number"], "+15550000001")
        self.assertEqual(
            signal_ingress_mod.resolve_signal_account_number(
                payload={"account_number": " +15550000002 "},
                config=None,
            ),
            "+15550000002",
        )
        self.assertEqual(
            signal_ingress_mod.resolve_signal_account_number(
                payload={"provider_context": {"account_number": " +15550000003 "}},
                config=None,
            ),
            "+15550000003",
        )
        self.assertIsNone(
            signal_ingress_mod.resolve_signal_account_number(
                payload={},
                config=None,
            )
        )
        self.assertIsNone(normalize_client_profile_id("not-a-uuid"))
        self.assertIsNone(client_profile_id_from_ingress_route({"client_profile_id": "bad"}))
        self.assertIsNone(get_active_client_profile_id())
        with client_profile_scope(_CLIENT_PROFILE_ID):
            self.assertEqual(get_active_client_profile_id(), _CLIENT_PROFILE_ID)
        self.assertIsNone(get_active_client_profile_id())

        fallback_entries = extractors.extract_signal_stage_entries(
            config=_signal_config(),
            payload={
                "provider_context": {
                    "client_profile_id": str(_CLIENT_PROFILE_ID),
                    "account_number": "+15550000004",
                },
                "params": {
                    "envelope": {
                        "sourceNumber": "+15550004",
                        "timestamp": 456,
                        "typingMessage": {},
                    }
                },
            },
        )
        self.assertEqual(len(fallback_entries), 1)
        self.assertEqual(fallback_entries[0].event.event_type, "typing")
        self.assertEqual(fallback_entries[0].event.identifier_value, "+15550000004")
        self.assertEqual(
            extractors.extract_signal_stage_entries(
                config=_signal_config(),
                payload={"params": {"envelope": {"timestamp": 1}}},
            ),
            [],
        )

    async def test_extractor_edge_branches_cover_callback_fallbacks_and_skips(
        self,
    ) -> None:
        with patch.object(
            extractors,
            "_resolve_ingress_route",
            new=AsyncMock(return_value=None),
        ):
            message_only_entries = await extractors.extract_telegram_stage_entries(
                path_token="telegram-path",
                payload={
                    "update_id": 42,
                    "message": {
                        "chat": {"id": 111},
                        "text": "hello",
                    },
                },
                relational_storage_gateway=object(),
                logging_gateway=Mock(),
            )
            callback_only_entries = await extractors.extract_telegram_stage_entries(
                path_token="telegram-path",
                payload={
                    "update_id": 43,
                    "callback_query": {
                        "message": {},
                    },
                },
                relational_storage_gateway=object(),
                logging_gateway=Mock(),
            )

            whatsapp_entries = await extractors.extract_whatsapp_stage_entries(
                path_token="whatsapp-path",
                payload={
                    "entry": [
                        {
                            "changes": "skip",
                        },
                        {
                            "changes": [
                                {"value": "skip"},
                                {
                                    "value": {
                                        "messages": [
                                            {
                                                "id": "wamid-2",
                                            }
                                        ],
                                        "contacts": [
                                            "skip",
                                            {"wa_id": "   "},
                                            {"wa_id": "contact-2"},
                                        ],
                                    }
                                },
                            ]
                        },
                    ]
                },
                relational_storage_gateway=object(),
                logging_gateway=Mock(),
            )

        self.assertEqual(message_only_entries, [])
        self.assertEqual(callback_only_entries, [])
        self.assertEqual(whatsapp_entries, [])
        self.assertEqual(
            signal_ingress_mod.signal_event_type({"dataMessage": {"message": "hello"}}),
            "message",
        )

    async def test_telegram_extractor_branch_paths_cover_single_message_and_callback(
        self,
    ) -> None:
        with patch.object(
            extractors,
            "_resolve_ingress_route",
            new=AsyncMock(return_value={"client_profile_id": str(_CLIENT_PROFILE_ID)}),
        ):
            message_only_entries = await extractors.extract_telegram_stage_entries(
                path_token="telegram-path",
                payload={
                    "update_id": 51,
                    "message": {
                        "chat": {"id": 111},
                        "text": "hello",
                    },
                },
                relational_storage_gateway=object(),
                logging_gateway=Mock(),
            )
            callback_only_entries = await extractors.extract_telegram_stage_entries(
                path_token="telegram-path",
                payload={
                    "update_id": 52,
                    "callback_query": {
                        "message": {"chat": {"id": 222}},
                    },
                },
                relational_storage_gateway=object(),
                logging_gateway=Mock(),
            )

        self.assertEqual(len(message_only_entries), 1)
        self.assertIsNone(message_only_entries[0].event.sender)
        self.assertEqual(len(callback_only_entries), 1)
        self.assertIsNone(callback_only_entries[0].event.sender)

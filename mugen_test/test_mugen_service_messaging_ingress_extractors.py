"""Unit tests for shared messaging ingress extractors."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from mugen.core.service import messaging_ingress_extractors as extractors
from mugen.core.service.context_scope_resolution import ContextScopeResolutionError


def _signal_config() -> SimpleNamespace:
    return SimpleNamespace(
        signal=SimpleNamespace(
            account="+15550000001",
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
                return_value={"runtime_profile_key": "profile-a"},
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

        self.assertEqual(route, {"runtime_profile_key": "profile-a"})
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
            new=AsyncMock(return_value={"runtime_profile_key": "line-a"}),
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
        self.assertEqual(entries[0].event.runtime_profile_key, "line-a")
        self.assertEqual(entries[0].event.event_id, "m-1")
        self.assertEqual(entries[0].event.sender, "U-1")
        self.assertEqual(entries[0].event.room_id, "U-1")
        self.assertEqual(entries[1].event.event_type, "postback")
        self.assertTrue(entries[1].event.dedupe_key.startswith("postback:"))

    async def test_telegram_extractor_covers_message_and_callback_query(self) -> None:
        with patch.object(
            extractors,
            "_resolve_ingress_route",
            new=AsyncMock(return_value=None),
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
        self.assertEqual(entries[0].event.runtime_profile_key, "default")
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
            new=AsyncMock(return_value={"runtime_profile_key": "wechat-a"}),
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
        self.assertEqual(event.runtime_profile_key, "wechat-a")
        self.assertEqual(event.event_type, "official_account:event")
        self.assertEqual(event.room_id, "wechat-user")
        self.assertEqual(event.provider_context["provider"], "official_account")

    async def test_whatsapp_extractor_covers_skips_messages_and_statuses(self) -> None:
        self.assertEqual(
            await extractors.extract_whatsapp_stage_entries(
                payload={},
                relational_storage_gateway=object(),
                logging_gateway=Mock(),
            ),
            [],
        )

        route_results = [
            {"runtime_profile_key": "wa-a"},
            None,
        ]

        async def _resolve_route(**_kwargs):
            return route_results.pop(0)

        with patch.object(
            extractors,
            "_resolve_ingress_route",
            new=AsyncMock(side_effect=_resolve_route),
        ):
            entries = await extractors.extract_whatsapp_stage_entries(
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
        self.assertEqual(message_event.runtime_profile_key, "wa-a")
        self.assertEqual(message_event.sender, "contact-wa")
        self.assertEqual(message_event.room_id, "contact-wa")
        self.assertEqual(message_event.identifier_value, "phone-1")
        status_event = entries[1].event
        self.assertEqual(status_event.runtime_profile_key, "default")
        self.assertEqual(status_event.event_type, "status")
        self.assertEqual(status_event.identifier_value, "phone-2")
        self.assertEqual(status_event.sender, "recipient-1")
        self.assertEqual(status_event.room_id, "recipient-1")

    async def test_whatsapp_extractor_preserves_sender_and_handles_empty_contacts(
        self,
    ) -> None:
        with patch.object(
            extractors,
            "_resolve_ingress_route",
            new=AsyncMock(return_value=None),
        ):
            entries = await extractors.extract_whatsapp_stage_entries(
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

        self.assertIsNone(
            extractors._signal_envelope({"params": []})  # pylint: disable=protected-access
        )
        envelope = {
            "sourceNumber": "+15550001",
            "timestamp": 123,
            "dataMessage": {"message": "hello"},
        }
        self.assertEqual(
            extractors._signal_envelope({"params": {"envelope": envelope}}),  # pylint: disable=protected-access
            envelope,
        )
        self.assertEqual(
            extractors._signal_sender({"sourceUuid": "uuid-1"}),  # pylint: disable=protected-access
            "uuid-1",
        )
        self.assertIsNone(
            extractors._signal_event_id({"timestamp": True})  # pylint: disable=protected-access
        )
        self.assertIsNone(
            extractors._signal_event_id({"timestamp": "bad"})  # pylint: disable=protected-access
        )
        self.assertEqual(
            extractors._signal_event_id({"timestamp": 5}),  # pylint: disable=protected-access
            "5",
        )
        self.assertEqual(
            extractors._signal_event_id(
                {"timestamp": 6, "source": "+15550002"}
            ),  # pylint: disable=protected-access
            "+15550002:6",
        )
        self.assertEqual(
            extractors._signal_event_type({"receiptMessage": {}}),  # pylint: disable=protected-access
            "receipt",
        )
        self.assertEqual(
            extractors._signal_event_type({"typingMessage": {}}),  # pylint: disable=protected-access
            "typing",
        )
        self.assertEqual(
            extractors._signal_event_type({"other": True}),  # pylint: disable=protected-access
            "event",
        )
        self.assertEqual(
            extractors._signal_event_type({"dataMessage": {"reaction": {}}}),  # pylint: disable=protected-access
            "reaction",
        )

        self.assertEqual(
            extractors._runtime_profile_key_from_route(  # pylint: disable=protected-access
                {"runtime_profile_key": "signal-a"}
            ),
            "signal-a",
        )
        self.assertEqual(
            extractors._runtime_profile_key_from_route(None),  # pylint: disable=protected-access
            "default",
        )
        self.assertEqual(
            extractors._runtime_profile_key_from_route(  # pylint: disable=protected-access
                {"runtime_profile_key": "   "}
            ),
            "default",
        )

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
                "runtime_profile_key": " default ",
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
        self.assertEqual(event.runtime_profile_key, "default")
        self.assertEqual(event.event_type, "reaction")
        self.assertEqual(event.event_id, "+15550001:123")
        self.assertEqual(event.identifier_value, "+15550000001")
        self.assertEqual(event.room_id, "+15550001")
        self.assertEqual(event.sender, "+15550001")
        self.assertEqual(event.provider_context["account_number"], "+15550000001")

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

        self.assertEqual(len(message_only_entries), 1)
        self.assertIsNone(message_only_entries[0].event.sender)
        self.assertEqual(len(callback_only_entries), 1)
        self.assertEqual(callback_only_entries[0].event.event_id, "43")
        self.assertIsNone(callback_only_entries[0].event.sender)
        self.assertEqual(len(whatsapp_entries), 1)
        self.assertEqual(whatsapp_entries[0].event.sender, "contact-2")
        self.assertIsNone(whatsapp_entries[0].event.identifier_value)
        self.assertEqual(
            extractors._signal_event_type(  # pylint: disable=protected-access
                {"dataMessage": {"message": "hello"}}
            ),
            "message",
        )

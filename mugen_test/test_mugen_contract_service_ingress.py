"""Unit tests for shared messaging ingress contracts."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest
import uuid

from mugen.core.contract.service.ingress import (
    MessagingIngressCheckpointUpdate,
    MessagingIngressEvent,
    MessagingIngressStageEntry,
)

_CLIENT_PROFILE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


class TestMugenContractServiceIngress(unittest.TestCase):
    """Covers normalization and validation branches for ingress contracts."""

    def test_event_normalizes_values_and_serializes(self) -> None:
        event = MessagingIngressEvent(
            version="1",
            platform=" matrix ",
            client_profile_id=f" {_CLIENT_PROFILE_ID} ",
            source_mode=" sync_room_message ",
            event_type=" RoomMessageText ",
            event_id="   ",
            dedupe_key=" dedupe ",
            identifier_type=" recipient_user_id ",
            identifier_value="   ",
            room_id=" !room:test ",
            sender=" @user:test ",
            payload={"body": "hello"},
            provider_context={"source": "worker"},
            received_at=datetime(2026, 3, 8, 12, 0, 0),
        )

        self.assertEqual(event.version, 1)
        self.assertEqual(event.platform, "matrix")
        self.assertEqual(event.client_profile_id, _CLIENT_PROFILE_ID)
        self.assertEqual(event.source_mode, "sync_room_message")
        self.assertEqual(event.event_type, "RoomMessageText")
        self.assertIsNone(event.event_id)
        self.assertEqual(event.dedupe_key, "dedupe")
        self.assertEqual(event.identifier_type, "recipient_user_id")
        self.assertIsNone(event.identifier_value)
        self.assertEqual(event.room_id, "!room:test")
        self.assertEqual(event.sender, "@user:test")
        self.assertEqual(event.payload, {"body": "hello"})
        self.assertEqual(event.provider_context, {"source": "worker"})
        self.assertEqual(event.received_at.tzinfo, timezone.utc)
        self.assertEqual(
            event.to_dict()["received_at"],
            "2026-03-08T12:00:00+00:00",
        )

        auto_now_event = MessagingIngressEvent(
            version=1,
            platform="matrix",
            client_profile_id=_CLIENT_PROFILE_ID,
            source_mode="sync_room_message",
            event_type="message",
            event_id=None,
            dedupe_key="dedupe",
            identifier_type="recipient_user_id",
            received_at=None,
        )
        self.assertEqual(auto_now_event.received_at.tzinfo, timezone.utc)

    def test_event_validation_errors_cover_normalizer_guards(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "MessagingIngressEvent.version must be positive",
        ):
            MessagingIngressEvent(
                version=0,
                platform="matrix",
                client_profile_id=_CLIENT_PROFILE_ID,
                source_mode="sync_room_message",
                event_type="message",
                event_id=None,
                dedupe_key="dedupe",
                identifier_type="recipient_user_id",
            )

        with self.assertRaisesRegex(
            TypeError,
            "MessagingIngressEvent.platform must be a string",
        ):
            MessagingIngressEvent(
                version=1,
                platform=object(),
                client_profile_id=_CLIENT_PROFILE_ID,
                source_mode="sync_room_message",
                event_type="message",
                event_id=None,
                dedupe_key="dedupe",
                identifier_type="recipient_user_id",
            )

        with self.assertRaisesRegex(
            ValueError,
            "MessagingIngressEvent.client_profile_id is required",
        ):
            MessagingIngressEvent(
                version=1,
                platform="matrix",
                client_profile_id="  ",
                source_mode="sync_room_message",
                event_type="message",
                event_id=None,
                dedupe_key="dedupe",
                identifier_type="recipient_user_id",
            )

        with self.assertRaisesRegex(
            TypeError,
            "MessagingIngressEvent.event_id must be a string when provided",
        ):
            MessagingIngressEvent(
                version=1,
                platform="matrix",
                client_profile_id=_CLIENT_PROFILE_ID,
                source_mode="sync_room_message",
                event_type="message",
                event_id=1,
                dedupe_key="dedupe",
                identifier_type="recipient_user_id",
            )

        with self.assertRaisesRegex(
            TypeError,
            "MessagingIngressEvent.payload must be a dict",
        ):
            MessagingIngressEvent(
                version=1,
                platform="matrix",
                client_profile_id=_CLIENT_PROFILE_ID,
                source_mode="sync_room_message",
                event_type="message",
                event_id=None,
                dedupe_key="dedupe",
                identifier_type="recipient_user_id",
                payload=[],
            )

        with self.assertRaisesRegex(
            TypeError,
            "MessagingIngressEvent.provider_context must be a dict",
        ):
            MessagingIngressEvent(
                version=1,
                platform="matrix",
                client_profile_id=_CLIENT_PROFILE_ID,
                source_mode="sync_room_message",
                event_type="message",
                event_id=None,
                dedupe_key="dedupe",
                identifier_type="recipient_user_id",
                provider_context=[],
            )

        with self.assertRaisesRegex(
            TypeError,
            "MessagingIngressEvent.received_at must be a datetime when provided",
        ):
            MessagingIngressEvent(
                version=1,
                platform="matrix",
                client_profile_id=_CLIENT_PROFILE_ID,
                source_mode="sync_room_message",
                event_type="message",
                event_id=None,
                dedupe_key="dedupe",
                identifier_type="recipient_user_id",
                received_at="bad",
            )

    def test_stage_entry_normalizes_and_validates(self) -> None:
        event = MessagingIngressEvent(
            version=1,
            platform="matrix",
            client_profile_id=_CLIENT_PROFILE_ID,
            source_mode="sync_room_message",
            event_type="message",
            event_id="$event",
            dedupe_key="message:$event",
            identifier_type="recipient_user_id",
        )

        entry = MessagingIngressStageEntry(
            ipc_command=" matrix_ingress_event ",
            event=event,
            dedupe_ttl_seconds="86400",
        )
        self.assertEqual(entry.ipc_command, "matrix_ingress_event")
        self.assertEqual(entry.dedupe_ttl_seconds, 86400)

        with self.assertRaisesRegex(
            TypeError,
            "MessagingIngressStageEntry.event must be MessagingIngressEvent",
        ):
            MessagingIngressStageEntry(
                ipc_command="matrix_ingress_event",
                event=object(),
            )

        with self.assertRaisesRegex(
            ValueError,
            "MessagingIngressStageEntry.dedupe_ttl_seconds must be positive",
        ):
            MessagingIngressStageEntry(
                ipc_command="matrix_ingress_event",
                event=event,
                dedupe_ttl_seconds=0,
            )

    def test_checkpoint_update_normalizes_and_validates(self) -> None:
        checkpoint = MessagingIngressCheckpointUpdate(
            platform=" matrix ",
            client_profile_id=f" {_CLIENT_PROFILE_ID} ",
            checkpoint_key=" sync_token ",
            checkpoint_value=" next-batch ",
            provider_context=None,
            observed_at=datetime(2026, 3, 8, 12, 30, 0),
        )

        self.assertEqual(checkpoint.platform, "matrix")
        self.assertEqual(checkpoint.client_profile_id, _CLIENT_PROFILE_ID)
        self.assertEqual(checkpoint.checkpoint_key, "sync_token")
        self.assertEqual(checkpoint.checkpoint_value, "next-batch")
        self.assertEqual(checkpoint.provider_context, {})
        self.assertEqual(checkpoint.observed_at.tzinfo, timezone.utc)

        with self.assertRaisesRegex(
            ValueError,
            "MessagingIngressCheckpointUpdate.platform is required",
        ):
            MessagingIngressCheckpointUpdate(
                platform="",
                client_profile_id=_CLIENT_PROFILE_ID,
                checkpoint_key="sync_token",
                checkpoint_value="next-batch",
            )

        with self.assertRaisesRegex(
            TypeError,
            "MessagingIngressCheckpointUpdate.provider_context must be a dict",
        ):
            MessagingIngressCheckpointUpdate(
                platform="matrix",
                client_profile_id=_CLIENT_PROFILE_ID,
                checkpoint_key="sync_token",
                checkpoint_value="next-batch",
                provider_context=[],
            )

        with self.assertRaisesRegex(
            TypeError,
            "MessagingIngressCheckpointUpdate.observed_at must be a datetime when provided",
        ):
            MessagingIngressCheckpointUpdate(
                platform="matrix",
                client_profile_id=_CLIENT_PROFILE_ID,
                checkpoint_key="sync_token",
                checkpoint_value="next-batch",
                observed_at="bad",
            )

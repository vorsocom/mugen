"""Unit tests for core domain entities and use-case interactors."""

import unittest

from mugen.core.domain.entity import ConversationEntity, ProcessingLifecycleEntity
from mugen.core.domain.use_case.enqueue_web_message import BuildQueuedMessageJobUseCase
from mugen.core.domain.use_case.normalize_composed_message import (
    NormalizeComposedMessageUseCase,
)
from mugen.core.domain.use_case.queue_job_lifecycle import QueueJobLifecycleUseCase
from mugen.core.domain.use_case.runtime_capability import (
    RuntimeCapabilityInput,
    evaluate_runtime_capabilities,
)


class TestDomainEntitiesAndUseCases(unittest.TestCase):
    """Covers domain validation and transition rules."""

    def test_conversation_entity_validates_inputs(self) -> None:
        entity = ConversationEntity.build(
            conversation_id=" convo-1 ",
            owner_user_id=" user-1 ",
        )
        self.assertEqual(entity.conversation_id, "convo-1")
        self.assertEqual(entity.owner_user_id, "user-1")

        with self.assertRaises(ValueError):
            ConversationEntity.build(conversation_id="", owner_user_id="user-1")
        with self.assertRaises(ValueError):
            ConversationEntity.build(conversation_id="convo-1", owner_user_id="")

    def test_processing_lifecycle_entity_validates_fields(self) -> None:
        entity = ProcessingLifecycleEntity.build(
            job_id="job-1",
            conversation_id="conv-1",
            sender="user-1",
        )
        self.assertEqual(entity.job_id, "job-1")

        with self.assertRaises(ValueError):
            ProcessingLifecycleEntity.build(
                job_id="",
                conversation_id="conv-1",
                sender="user-1",
            )

    def test_build_queued_message_job_use_case(self) -> None:
        use_case = BuildQueuedMessageJobUseCase.with_defaults()
        job = use_case.handle(
            job_id="job-1",
            auth_user="user-1",
            conversation_id="conv-1",
            message_type="text",
            text="hello",
            metadata={"x": 1},
            file_path=None,
            mime_type=None,
            original_filename=None,
            client_message_id="cid-1",
        )
        payload = job.as_pending_record(now_iso="2026-01-01T00:00:00+00:00")
        self.assertEqual(payload["status"], "pending")
        self.assertEqual(payload["message_type"], "text")

        with self.assertRaises(ValueError):
            use_case.handle(
                job_id="job-2",
                auth_user="user-1",
                conversation_id="conv-1",
                message_type="text",
                text=" ",
                metadata=None,
                file_path=None,
                mime_type=None,
                original_filename=None,
                client_message_id="cid-2",
            )

        with self.assertRaises(ValueError):
            use_case.handle(
                job_id="job-3",
                auth_user="user-1",
                conversation_id="conv-1",
                message_type="audio",
                text=None,
                metadata=None,
                file_path=None,
                mime_type=None,
                original_filename=None,
                client_message_id="cid-3",
            )

        with self.assertRaises(ValueError):
            use_case.handle(
                job_id="job-4",
                auth_user="user-1",
                conversation_id="conv-1",
                message_type="bad",
                text=None,
                metadata=None,
                file_path=None,
                mime_type=None,
                original_filename=None,
                client_message_id="cid-4",
            )

        with self.assertRaises(ValueError):
            use_case.handle(
                job_id=" ",
                auth_user="user-1",
                conversation_id="conv-1",
                message_type="text",
                text="hello",
                metadata=None,
                file_path=None,
                mime_type=None,
                original_filename=None,
                client_message_id="cid-5",
            )

        with self.assertRaises(ValueError):
            use_case.handle(
                job_id="job-5",
                auth_user="user-1",
                conversation_id="conv-1",
                message_type="text",
                text="hello",
                metadata=None,
                file_path=None,
                mime_type=None,
                original_filename=None,
                client_message_id=" ",
            )

        with self.assertRaises(ValueError):
            use_case.handle(
                job_id="job-6",
                auth_user="user-1",
                conversation_id="conv-1",
                message_type=None,  # type: ignore[arg-type]
                text="hello",
                metadata=None,
                file_path=None,
                mime_type=None,
                original_filename=None,
                client_message_id="cid-6",
            )

        with self.assertRaises(ValueError):
            use_case.handle(
                job_id="job-7",
                auth_user="user-1",
                conversation_id="conv-1",
                message_type=" ",
                text="hello",
                metadata=None,
                file_path=None,
                mime_type=None,
                original_filename=None,
                client_message_id="cid-7",
            )

    def test_normalize_composed_message_use_case(self) -> None:
        use_case = NormalizeComposedMessageUseCase()
        normalized = use_case.handle(
            {
                "composition_mode": "message_with_attachments",
                "parts": [
                    {"type": "text", "text": "hello"},
                    {"type": "attachment", "id": "a1"},
                ],
                "attachments": [
                    {
                        "id": "a1",
                        "file_path": "/tmp/a1",
                        "mime_type": "image/png",
                        "metadata": {},
                        "caption": "cap",
                    }
                ],
            }
        )
        self.assertEqual(normalized["composition_mode"], "message_with_attachments")
        self.assertEqual(len(normalized["attachments"]), 1)

        with self.assertRaises(ValueError):
            use_case.handle({"composition_mode": "attachment_with_caption"})

        limited_use_case = NormalizeComposedMessageUseCase(max_attachments=1)
        with self.assertRaises(ValueError):
            limited_use_case.handle(
                {
                    "composition_mode": "message_with_attachments",
                    "parts": [
                        {"type": "attachment", "id": "a1"},
                        {"type": "attachment", "id": "a2"},
                    ],
                    "attachments": [
                        {"id": "a1", "file_path": "/tmp/a1"},
                        {"id": "a2", "file_path": "/tmp/a2"},
                    ],
                }
            )

    def test_queue_job_lifecycle_use_case(self) -> None:
        use_case = QueueJobLifecycleUseCase()
        pending = {"id": "job-1", "status": "pending", "attempts": 0}

        claimed = use_case.claim(
            job=pending,
            now_iso="2026-01-01T00:00:00+00:00",
            lease_expires_at=123.0,
        )
        self.assertEqual(claimed["status"], "processing")
        self.assertEqual(claimed["attempts"], 1)

        done = use_case.complete(
            job=claimed,
            now_iso="2026-01-01T00:01:00+00:00",
        )
        self.assertEqual(done["status"], "done")

        failed = use_case.fail(
            job=claimed,
            now_iso="2026-01-01T00:02:00+00:00",
            error="boom",
        )
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"], "boom")

        with self.assertRaises(ValueError):
            use_case.claim(
                job={"status": "done"},
                now_iso="2026-01-01T00:03:00+00:00",
                lease_expires_at=123.0,
            )

        with self.assertRaises(ValueError):
            use_case.complete(job="bad", now_iso="2026-01-01T00:03:00+00:00")

    def test_runtime_capability_use_case(self) -> None:
        healthy = evaluate_runtime_capabilities(
            RuntimeCapabilityInput(
                active_platforms=["web", "matrix"],
                messaging_handler_platforms=[[]],
                mh_mode="required",
                has_web_client_runtime_path=True,
                container_ready=True,
                provider_ready=True,
            )
        )
        self.assertTrue(healthy.healthy)
        self.assertEqual(healthy.statuses["messaging.mh.mode"], "healthy")
        self.assertEqual(healthy.statuses["messaging.mh.availability"], "healthy")
        self.assertEqual(healthy.statuses["messaging.mh.web"], "healthy")
        self.assertEqual(healthy.statuses["messaging.mh.matrix"], "healthy")

        degraded = evaluate_runtime_capabilities(
            RuntimeCapabilityInput(
                active_platforms=["web", "whatsapp"],
                messaging_handler_platforms=[["web"]],
                mh_mode="required",
                has_web_client_runtime_path=False,
                container_ready=True,
                provider_ready=False,
            )
        )
        self.assertFalse(degraded.healthy)
        self.assertIn("provider_readiness", degraded.failed_capabilities)
        self.assertIn("messaging.mh.whatsapp", degraded.failed_capabilities)
        self.assertIn("web.client_runtime_path", degraded.failed_capabilities)

        optional_zero_mh = evaluate_runtime_capabilities(
            RuntimeCapabilityInput(
                active_platforms=["web", "whatsapp"],
                messaging_handler_platforms=[],
                mh_mode="optional",
                has_web_client_runtime_path=True,
                container_ready=True,
                provider_ready=True,
            )
        )
        self.assertTrue(optional_zero_mh.healthy)
        self.assertEqual(
            optional_zero_mh.statuses["messaging.mh.availability"],
            "healthy",
        )
        self.assertEqual(optional_zero_mh.statuses["messaging.mh.web"], "healthy")
        self.assertEqual(
            optional_zero_mh.statuses["messaging.mh.whatsapp"],
            "healthy",
        )

    def test_runtime_capability_use_case_normalizes_edge_inputs(self) -> None:
        non_collection_platforms = evaluate_runtime_capabilities(
            RuntimeCapabilityInput(
                active_platforms="web",  # type: ignore[arg-type]
                messaging_handler_platforms="bad",  # type: ignore[arg-type]
                mh_mode="optional",
                has_web_client_runtime_path=True,
            )
        )
        self.assertEqual(
            set(non_collection_platforms.statuses.keys()),
            {
                "container_readiness",
                "provider_readiness",
                "messaging.mh.mode",
                "messaging.mh.availability",
            },
        )

        mixed_scopes = evaluate_runtime_capabilities(
            RuntimeCapabilityInput(
                active_platforms=["unknown", "whatsapp", " WHATSAPP ", ""],
                messaging_handler_platforms=[None, object(), ["whatsapp"]],
                mh_mode="optional",
                has_web_client_runtime_path=True,
            )
        )
        self.assertTrue(mixed_scopes.healthy)
        self.assertEqual(mixed_scopes.statuses["messaging.mh.whatsapp"], "healthy")

        invalid_mode = evaluate_runtime_capabilities(
            RuntimeCapabilityInput(
                active_platforms=["web"],
                messaging_handler_platforms=[object()],
                mh_mode="legacy",
                has_web_client_runtime_path=True,
            )
        )
        self.assertFalse(invalid_mode.healthy)
        self.assertIn("messaging.mh.mode", invalid_mode.failed_capabilities)
        self.assertIn("messaging.mh.availability", invalid_mode.failed_capabilities)
        self.assertIn("messaging.mh.web", invalid_mode.failed_capabilities)

        optional_provider_degraded = evaluate_runtime_capabilities(
            RuntimeCapabilityInput(
                active_platforms=["matrix"],
                messaging_handler_platforms=[["matrix"]],
                mh_mode="required",
                has_web_client_runtime_path=True,
                container_ready=True,
                provider_ready=True,
                optional_provider_failures={
                    "email_gateway": "smtp unavailable",
                    "knowledge_gateway": "   ",
                },
            )
        )
        self.assertTrue(optional_provider_degraded.healthy)
        self.assertEqual(
            optional_provider_degraded.statuses["provider_readiness.optional.email_gateway"],
            "degraded",
        )
        self.assertEqual(
            optional_provider_degraded.errors["provider_readiness.optional.email_gateway"],
            "smtp unavailable",
        )
        self.assertEqual(
            optional_provider_degraded.errors["provider_readiness.optional.knowledge_gateway"],
            "Optional provider readiness check failed.",
        )


if __name__ == "__main__":
    unittest.main()

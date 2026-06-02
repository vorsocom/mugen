"""Unit tests for human handoff event stream endpoint."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import uuid

from quart import Quart
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import BadRequest, Forbidden, InternalServerError

from mugen.core.plugin.channel_orchestration.api import (
    human_handoff_events as handoff_events_api,
)


async def _empty_stream():
    if False:
        yield ""


class TestMugenChannelOrchestrationHandoffEventsApi(
    unittest.IsolatedAsyncioTestCase
):
    """Covers handoff event stream endpoint behavior."""

    def test_default_providers_delegate_to_di_container(self) -> None:
        logger = object()
        auth_svc = object()
        handoff_svc = object()

        def _service_for_key(key):
            return {
                handoff_events_api.di.EXT_SERVICE_ADMIN_SVC_AUTH: auth_svc,
                handoff_events_api.di.EXT_SERVICE_HUMAN_HANDOFF: handoff_svc,
            }[key]

        container = SimpleNamespace(
            logging_gateway=logger,
            get_required_ext_service=Mock(side_effect=_service_for_key),
        )

        with patch.object(handoff_events_api.di, "container", container):
            self.assertIs(handoff_events_api._logger_provider(), logger)
            self.assertIs(handoff_events_api._auth_provider(), auth_svc)
            self.assertIs(
                handoff_events_api._handoff_service_provider(),
                handoff_svc,
            )

        self.assertEqual(container.get_required_ext_service.call_count, 2)

    def test_optional_helpers_normalize_empty_values(self) -> None:
        self.assertIsNone(
            handoff_events_api._optional_uuid(None, field_name="session_id")
        )
        self.assertIsNone(
            handoff_events_api._optional_uuid("", field_name="session_id")
        )
        self.assertIsNone(handoff_events_api._optional_text(None))

    async def test_handoff_events_stream_checks_permission_and_returns_sse(
        self,
    ) -> None:
        app = Quart("handoff_events_stream_test")
        tenant_id = uuid.uuid4()
        auth_user = uuid.uuid4()
        session_id = uuid.uuid4()
        auth_svc = SimpleNamespace(has_permission=AsyncMock(return_value=True))
        handoff_service = SimpleNamespace(
            stream_handoff_events=AsyncMock(return_value=_empty_stream())
        )

        async with app.test_request_context(
            (
                f"/api/core/acp/v1/tenants/{tenant_id}/"
                "HumanHandoffEvents/stream"
                f"?last_event_id=query-cursor&session_id={session_id}&status=active"
            ),
            headers={"Last-Event-ID": "header-cursor"},
        ):
            response = await handoff_events_api.human_handoff_events_stream.__wrapped__(
                tenant_id=str(tenant_id),
                auth_user=str(auth_user),
                logger_provider=lambda: SimpleNamespace(error=Mock()),
                auth_provider=lambda: auth_svc,
                handoff_service_provider=lambda: handoff_service,
            )

        auth_svc.has_permission.assert_awaited_once_with(
            user_id=auth_user,
            permission_object=handoff_events_api.HUMAN_HANDOFF_OPERATOR_PERMISSION,
            permission_type=handoff_events_api.HUMAN_HANDOFF_OPERATOR_PERMISSION,
            tenant_id=tenant_id,
        )
        handoff_service.stream_handoff_events.assert_awaited_once_with(
            tenant_id=tenant_id,
            last_event_id="header-cursor",
            session_id=session_id,
            status="active",
        )
        self.assertEqual(response.mimetype, "text/event-stream")
        self.assertEqual(response.headers["Cache-Control"], "no-cache")
        self.assertEqual(response.headers["X-Accel-Buffering"], "no")

    async def test_handoff_events_stream_denies_missing_operator_permission(
        self,
    ) -> None:
        app = Quart("handoff_events_stream_denied_test")
        tenant_id = uuid.uuid4()
        auth_svc = SimpleNamespace(has_permission=AsyncMock(return_value=False))

        async with app.test_request_context(
            f"/api/core/acp/v1/tenants/{tenant_id}/HumanHandoffEvents/stream",
        ):
            with self.assertRaises(Forbidden):
                await handoff_events_api.human_handoff_events_stream.__wrapped__(
                    tenant_id=str(tenant_id),
                    auth_user=str(uuid.uuid4()),
                    logger_provider=lambda: SimpleNamespace(error=Mock()),
                    auth_provider=lambda: auth_svc,
                    handoff_service_provider=lambda: SimpleNamespace(),
                )

    async def test_handoff_events_stream_rejects_invalid_session_id(self) -> None:
        app = Quart("handoff_events_stream_invalid_session_test")
        tenant_id = uuid.uuid4()
        auth_svc = SimpleNamespace(has_permission=AsyncMock(return_value=True))

        async with app.test_request_context(
            (
                f"/api/core/acp/v1/tenants/{tenant_id}/"
                "HumanHandoffEvents/stream?session_id=not-a-uuid"
            ),
        ):
            with self.assertRaises(BadRequest):
                await handoff_events_api.human_handoff_events_stream.__wrapped__(
                    tenant_id=str(tenant_id),
                    auth_user=str(uuid.uuid4()),
                    logger_provider=lambda: SimpleNamespace(error=Mock()),
                    auth_provider=lambda: auth_svc,
                    handoff_service_provider=lambda: SimpleNamespace(),
                )

    async def test_handoff_events_stream_rejects_invalid_path_uuid(self) -> None:
        app = Quart("handoff_events_stream_invalid_path_test")

        async with app.test_request_context(
            "/api/core/acp/v1/tenants/not-a-uuid/HumanHandoffEvents/stream",
        ):
            with self.assertRaises(BadRequest):
                await handoff_events_api.human_handoff_events_stream.__wrapped__(
                    tenant_id="not-a-uuid",
                    auth_user=str(uuid.uuid4()),
                    logger_provider=lambda: SimpleNamespace(error=Mock()),
                    auth_provider=lambda: SimpleNamespace(),
                    handoff_service_provider=lambda: SimpleNamespace(),
                )

    async def test_handoff_events_stream_maps_service_errors(self) -> None:
        app = Quart("handoff_events_stream_errors_test")
        tenant_id = uuid.uuid4()
        auth_user = uuid.uuid4()

        cases = [
            (SQLAlchemyError("db failed"), InternalServerError, True),
            (ValueError("bad cursor"), BadRequest, False),
            (RuntimeError("boom"), InternalServerError, True),
        ]
        for exc, expected_error, logs_error in cases:
            with self.subTest(exc=type(exc).__name__):
                auth_svc = SimpleNamespace(
                    has_permission=AsyncMock(return_value=True)
                )
                logger = SimpleNamespace(error=Mock())
                handoff_service = SimpleNamespace(
                    stream_handoff_events=AsyncMock(side_effect=exc)
                )

                async with app.test_request_context(
                    (
                        f"/api/core/acp/v1/tenants/{tenant_id}/"
                        "HumanHandoffEvents/stream"
                    ),
                ):
                    with self.assertRaises(expected_error):
                        await (
                            handoff_events_api.human_handoff_events_stream
                            .__wrapped__(
                                tenant_id=str(tenant_id),
                                auth_user=str(auth_user),
                                logger_provider=lambda: logger,
                                auth_provider=lambda: auth_svc,
                                handoff_service_provider=lambda: handoff_service,
                            )
                        )

                self.assertEqual(logger.error.called, logs_error)


if __name__ == "__main__":
    unittest.main()

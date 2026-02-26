"""Focused behavior tests for ops_connector ConnectorInstanceService actions."""

import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from mugen.core.plugin.acp.contract.service.key_provider import ResolvedKeyMaterial
from mugen.core.plugin.ops_connector.api.validation import (
    ConnectorInstanceInvokeValidation,
    ConnectorInstanceTestConnectionValidation,
)
from mugen.core.plugin.ops_connector.domain import ConnectorInstanceDE, ConnectorTypeDE
from mugen.core.plugin.ops_connector.service.connector_instance import (
    ConnectorInstanceService,
)


class TestConnectorInstanceService(unittest.IsolatedAsyncioTestCase):
    """Tests invoke/test_connection happy/error branches with internal mocks."""

    @staticmethod
    def _service() -> ConnectorInstanceService:
        return ConnectorInstanceService(table="ops_connector_instance", rsg=Mock())

    @staticmethod
    def _instance() -> ConnectorInstanceDE:
        return ConnectorInstanceDE(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            connector_type_id=uuid.uuid4(),
            row_version=5,
            display_name="Connector",
            config_json={
                "BaseUrl": "http://127.0.0.1:8081",
                "HealthPath": "/api/core/acp/v1/auth/.well-known/jwks.json",
            },
            secret_ref="ops_connector_default",
            status="active",
        )

    @staticmethod
    def _connector_type() -> ConnectorTypeDE:
        return ConnectorTypeDE(
            id=uuid.uuid4(),
            key="http_json_default",
            display_name="HTTP JSON Default",
            adapter_kind="http_json",
            capabilities_json={
                "get_jwks": {
                    "Method": "GET",
                    "PathTemplate": "/api/core/acp/v1/auth/.well-known/jwks.json",
                    "InputPlacement": "query",
                }
            },
            is_active=True,
        )

    async def test_action_invoke_returns_replay_response_when_dedup_replays(
        self,
    ) -> None:
        svc = self._service()
        tenant_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()

        instance = self._instance()
        connector_type = self._connector_type()

        svc._emit_connector_biz_trace = AsyncMock()  # type: ignore[attr-defined]
        svc._get_for_action = AsyncMock(  # type: ignore[attr-defined]
            return_value=instance
        )
        svc._resolve_connector_type = AsyncMock(  # type: ignore[attr-defined]
            return_value=connector_type
        )
        svc._resolve_capability = Mock(  # type: ignore[attr-defined]
            return_value=("get_jwks", {})
        )
        svc._acquire_dedup = AsyncMock(  # type: ignore[attr-defined]
            return_value={
                "enabled": True,
                "record_id": uuid.uuid4(),
                "replay": ({"Status": "ok", "Idempotent": True}, 200),
            }
        )

        payload, code = await svc.action_invoke(
            tenant_id=tenant_id,
            entity_id=entity_id,
            where={"tenant_id": tenant_id, "id": entity_id},
            auth_user_id=auth_user_id,
            data=ConnectorInstanceInvokeValidation(
                row_version=5,
                capability_name="get_jwks",
                input_json={},
                client_action_key="dedup-key",
            ),
        )

        self.assertEqual(code, 200)
        self.assertEqual(payload["Status"], "ok")
        self.assertTrue(payload["Idempotent"])

    async def test_action_invoke_success_returns_envelope_and_commits_dedup(
        self,
    ) -> None:
        svc = self._service()
        tenant_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        call_log_id = uuid.uuid4()

        instance = self._instance()
        connector_type = self._connector_type()

        svc._emit_connector_biz_trace = AsyncMock()  # type: ignore[attr-defined]
        svc._get_for_action = AsyncMock(  # type: ignore[attr-defined]
            return_value=instance
        )
        svc._resolve_connector_type = AsyncMock(  # type: ignore[attr-defined]
            return_value=connector_type
        )
        svc._resolve_capability = Mock(  # type: ignore[attr-defined]
            return_value=(
                "get_jwks",
                {
                    "Method": "GET",
                    "PathTemplate": "/api/core/acp/v1/auth/.well-known/jwks.json",
                    "InputPlacement": "query",
                },
            )
        )
        svc._acquire_dedup = AsyncMock(  # type: ignore[attr-defined]
            return_value={
                "enabled": True,
                "record_id": uuid.uuid4(),
                "replay": None,
            }
        )
        svc._validate_input_schema = AsyncMock()  # type: ignore[attr-defined]
        svc._resolve_secret_material = AsyncMock(  # type: ignore[attr-defined]
            return_value=ResolvedKeyMaterial(
                key_id="ops_connector_default",
                secret=b"dev-ops-connector-secret",
                provider="local",
            )
        )
        svc._resolve_base_url = Mock(  # type: ignore[attr-defined]
            return_value="http://127.0.0.1:8081"
        )
        svc._resolve_retry_policy = Mock(  # type: ignore[attr-defined]
            return_value=(10.0, 0, 0.0, (429, 500))
        )
        svc._invoke_request_spec = Mock(  # type: ignore[attr-defined]
            return_value=(
                "GET",
                "http://127.0.0.1:8081/api/core/acp/v1/auth/.well-known/jwks.json",
                {},
                {},
                None,
                None,
            )
        )
        svc._resolve_headers = Mock(return_value={})  # type: ignore[attr-defined]
        svc._execute_http_request = AsyncMock(  # type: ignore[attr-defined]
            return_value={
                "ok": True,
                "status_code": 200,
                "payload": {"keys": []},
                "attempt_count": 1,
                "timeout": False,
                "transport_error": None,
            }
        )
        svc._validate_output_schema = AsyncMock(  # type: ignore[attr-defined]
            return_value=[]
        )
        svc._persist_call_log = AsyncMock(  # type: ignore[attr-defined]
            return_value=call_log_id
        )
        svc._commit_dedup_success = AsyncMock()  # type: ignore[attr-defined]

        payload, code = await svc.action_invoke(
            tenant_id=tenant_id,
            entity_id=entity_id,
            where={"tenant_id": tenant_id, "id": entity_id},
            auth_user_id=auth_user_id,
            data=ConnectorInstanceInvokeValidation(
                row_version=5,
                capability_name="get_jwks",
                input_json={},
                client_action_key="dedup-key",
            ),
        )

        self.assertEqual(code, 200)
        self.assertEqual(payload["Status"], "ok")
        self.assertEqual(payload["HttpStatusCode"], 200)
        self.assertEqual(payload["AttemptCount"], 1)
        self.assertEqual(payload["ConnectorCallLogId"], str(call_log_id))
        svc._commit_dedup_success.assert_awaited_once()  # type: ignore[attr-defined]

    async def test_action_invoke_timeout_failure_returns_504_and_commits_failure(
        self,
    ) -> None:
        svc = self._service()
        tenant_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        call_log_id = uuid.uuid4()

        instance = self._instance()
        connector_type = self._connector_type()

        svc._emit_connector_biz_trace = AsyncMock()  # type: ignore[attr-defined]
        svc._get_for_action = AsyncMock(  # type: ignore[attr-defined]
            return_value=instance
        )
        svc._resolve_connector_type = AsyncMock(  # type: ignore[attr-defined]
            return_value=connector_type
        )
        svc._resolve_capability = Mock(  # type: ignore[attr-defined]
            return_value=(
                "get_jwks",
                {
                    "Method": "GET",
                    "PathTemplate": "/api/core/acp/v1/auth/.well-known/jwks.json",
                    "InputPlacement": "query",
                },
            )
        )
        svc._acquire_dedup = AsyncMock(  # type: ignore[attr-defined]
            return_value={
                "enabled": True,
                "record_id": uuid.uuid4(),
                "replay": None,
            }
        )
        svc._validate_input_schema = AsyncMock()  # type: ignore[attr-defined]
        svc._resolve_secret_material = AsyncMock(  # type: ignore[attr-defined]
            return_value=ResolvedKeyMaterial(
                key_id="ops_connector_default",
                secret=b"dev-ops-connector-secret",
                provider="local",
            )
        )
        svc._resolve_base_url = Mock(  # type: ignore[attr-defined]
            return_value="http://127.0.0.1:8081"
        )
        svc._resolve_retry_policy = Mock(  # type: ignore[attr-defined]
            return_value=(10.0, 0, 0.0, (429, 500))
        )
        svc._invoke_request_spec = Mock(  # type: ignore[attr-defined]
            return_value=(
                "GET",
                "http://127.0.0.1:8081/api/core/acp/v1/auth/.well-known/jwks.json",
                {},
                {},
                None,
                None,
            )
        )
        svc._resolve_headers = Mock(return_value={})  # type: ignore[attr-defined]
        svc._execute_http_request = AsyncMock(  # type: ignore[attr-defined]
            return_value={
                "ok": False,
                "status_code": 504,
                "payload": None,
                "attempt_count": 3,
                "timeout": True,
                "transport_error": "request timeout",
            }
        )
        svc._run_failure_escalation = AsyncMock(  # type: ignore[attr-defined]
            return_value={"Attempted": True}
        )
        svc._persist_call_log = AsyncMock(  # type: ignore[attr-defined]
            return_value=call_log_id
        )
        svc._commit_dedup_failure = AsyncMock()  # type: ignore[attr-defined]

        payload, code = await svc.action_invoke(
            tenant_id=tenant_id,
            entity_id=entity_id,
            where={"tenant_id": tenant_id, "id": entity_id},
            auth_user_id=auth_user_id,
            data=ConnectorInstanceInvokeValidation(
                row_version=5,
                capability_name="get_jwks",
                input_json={},
                client_action_key="dedup-key",
            ),
        )

        self.assertEqual(code, 504)
        self.assertEqual(payload["Status"], "failed")
        self.assertEqual(payload["AttemptCount"], 3)
        self.assertEqual(payload["ConnectorCallLogId"], str(call_log_id))
        svc._commit_dedup_failure.assert_awaited_once()  # type: ignore[attr-defined]

    async def test_action_test_connection_success_returns_expected_envelope(
        self,
    ) -> None:
        svc = self._service()
        tenant_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        auth_user_id = uuid.uuid4()
        call_log_id = uuid.uuid4()

        instance = self._instance()
        connector_type = self._connector_type()

        svc._get_for_action = AsyncMock(  # type: ignore[attr-defined]
            return_value=instance
        )
        svc._resolve_connector_type = AsyncMock(  # type: ignore[attr-defined]
            return_value=connector_type
        )
        svc._resolve_secret_material = AsyncMock(  # type: ignore[attr-defined]
            return_value=ResolvedKeyMaterial(
                key_id="ops_connector_default",
                secret=b"dev-ops-connector-secret",
                provider="local",
            )
        )
        svc._resolve_base_url = Mock(  # type: ignore[attr-defined]
            return_value="http://127.0.0.1:8081"
        )
        svc._resolve_retry_policy = Mock(  # type: ignore[attr-defined]
            return_value=(10.0, 0, 0.0, ())
        )
        svc._resolve_headers = Mock(return_value={})  # type: ignore[attr-defined]
        svc._execute_http_request = AsyncMock(  # type: ignore[attr-defined]
            return_value={
                "ok": True,
                "status_code": 200,
                "payload": {"keys": []},
                "attempt_count": 1,
                "timeout": False,
                "transport_error": None,
            }
        )
        svc._persist_call_log = AsyncMock(  # type: ignore[attr-defined]
            return_value=call_log_id
        )

        payload, code = await svc.action_test_connection(
            tenant_id=tenant_id,
            entity_id=entity_id,
            where={"tenant_id": tenant_id, "id": entity_id},
            auth_user_id=auth_user_id,
            data=ConnectorInstanceTestConnectionValidation(
                row_version=5,
                trace_id="trace-test",
            ),
        )

        self.assertEqual(code, 200)
        self.assertTrue(payload["Ok"])
        self.assertEqual(payload["StatusCode"], 200)
        self.assertEqual(payload["ConnectorCallLogId"], str(call_log_id))

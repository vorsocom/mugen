"""Validation tests for ops_connector Phase 6 payload contracts."""

import unittest
import uuid

from pydantic import ValidationError

from mugen.core.plugin.ops_connector.api.validation import (
    ConnectorInstanceCreateValidation,
    ConnectorInstanceInvokeValidation,
    ConnectorInstanceTestConnectionValidation,
    ConnectorRetryPolicyValidation,
    ConnectorTypeCreateValidation,
    ConnectorTypeUpdateValidation,
)


class TestOpsConnectorPhase6Validations(unittest.TestCase):
    """Covers validation branches introduced for Phase 6."""

    def test_connector_type_create_validation_accepts_http_json_shape(self) -> None:
        payload = ConnectorTypeCreateValidation(
            key="http_test",
            display_name="HTTP Test",
            adapter_kind="http_json",
            capabilities_json={
                "invoke_probe": {
                    "Method": "post",
                    "PathTemplate": "/v1/probe/{ProbeId}",
                    "Headers": {"X-Api-Key": "{secret}"},
                    "RetryStatusCodes": [429, 500],
                    "InputSchema": {
                        "Key": "ops.connector.input",
                        "Version": 1,
                    },
                    "OutputSchema": {
                        "SchemaDefinitionId": str(uuid.uuid4()),
                    },
                }
            },
        )

        self.assertEqual(payload.key, "http_test")
        self.assertEqual(payload.display_name, "HTTP Test")
        self.assertEqual(payload.adapter_kind, "http_json")

    def test_connector_type_create_validation_rejects_invalid_shapes(self) -> None:
        with self.assertRaises(ValidationError):
            ConnectorTypeCreateValidation(
                key="x",
                display_name="X",
                adapter_kind="websocket",
            )

        with self.assertRaises(ValidationError):
            ConnectorTypeCreateValidation(
                key="x",
                display_name="X",
                capabilities_json={
                    "probe": {
                        "PathTemplate": "v1/no-leading-slash",
                    }
                },
            )

        with self.assertRaises(ValidationError):
            ConnectorTypeCreateValidation(
                key="x",
                display_name="X",
                capabilities_json={
                    "probe": {
                        "Headers": [],
                    }
                },
            )

        with self.assertRaises(ValidationError):
            ConnectorTypeCreateValidation(
                key="x",
                display_name="X",
                capabilities_json={
                    "probe": {
                        "InputSchema": {"Key": "ops.connector.input"},
                    }
                },
            )

    def test_connector_type_create_validation_rejects_empty_text(self) -> None:
        with self.assertRaises(ValidationError):
            ConnectorTypeCreateValidation(
                key=" ",
                display_name="X",
            )

        with self.assertRaises(ValidationError):
            ConnectorTypeCreateValidation(
                key="x",
                display_name=" ",
            )

    def test_connector_type_create_validation_rejects_capability_errors(self) -> None:
        with self.assertRaises(ValidationError):
            ConnectorTypeCreateValidation(
                key="x",
                display_name="X",
                adapter_kind="grpc",
            )

        with self.assertRaises(ValidationError):
            ConnectorTypeCreateValidation(
                key="x",
                display_name="X",
                capabilities_json=[],
            )

        with self.assertRaises(ValidationError):
            ConnectorTypeCreateValidation(
                key="x",
                display_name="X",
                capabilities_json={" ": {}},
            )

        with self.assertRaises(ValidationError):
            ConnectorTypeCreateValidation(
                key="x",
                display_name="X",
                capabilities_json={"probe": "not-an-object"},
            )

        with self.assertRaises(ValidationError):
            ConnectorTypeCreateValidation(
                key="x",
                display_name="X",
                capabilities_json={"probe": {"RetryStatusCodes": []}},
            )

        with self.assertRaises(ValidationError):
            ConnectorTypeCreateValidation(
                key="x",
                display_name="X",
                capabilities_json={"probe": {"RetryStatusCodes": [429, "nope"]}},
            )

        with self.assertRaises(ValidationError):
            ConnectorTypeCreateValidation(
                key="x",
                display_name="X",
                capabilities_json={"probe": {"RetryStatusCodes": [99]}},
            )

    def test_connector_type_create_validation_rejects_schema_reference_errors(
        self,
    ) -> None:
        with self.assertRaises(ValidationError):
            ConnectorTypeCreateValidation(
                key="x",
                display_name="X",
                capabilities_json={"probe": {"InputSchema": 1}},
            )

        with self.assertRaises(ValidationError):
            ConnectorTypeCreateValidation(
                key="x",
                display_name="X",
                capabilities_json={
                    "probe": {"OutputSchema": {"SchemaDefinitionId": "not-a-uuid"}}
                },
            )

        with self.assertRaises(ValidationError):
            ConnectorTypeCreateValidation(
                key="x",
                display_name="X",
                capabilities_json={"probe": {"InputSchema": {}}},
            )

        with self.assertRaises(ValidationError):
            ConnectorTypeCreateValidation(
                key="x",
                display_name="X",
                capabilities_json={
                    "probe": {
                        "InputSchema": {"Key": "ops.connector.input", "Version": 0}
                    }
                },
            )

        with self.assertRaises(ValidationError):
            ConnectorTypeCreateValidation(
                key="x",
                display_name="X",
                capabilities_json={
                    "probe": {
                        "InputSchema": {"Key": "ops.connector.input", "Version": "x"}
                    }
                },
            )

    def test_connector_type_update_validation_accepts_partial_payload(self) -> None:
        payload = ConnectorTypeUpdateValidation(
            display_name="  Updated Connector  ",
            is_active=False,
        )
        self.assertEqual(payload.display_name, "Updated Connector")
        self.assertFalse(payload.is_active)

    def test_connector_type_update_validation_accepts_http_json_adapter_kind(
        self,
    ) -> None:
        payload = ConnectorTypeUpdateValidation(adapter_kind=" HTTP_JSON ")
        self.assertEqual(payload.adapter_kind, "http_json")

    def test_connector_type_update_validation_accepts_non_empty_key(self) -> None:
        payload = ConnectorTypeUpdateValidation(key=" connector_key ")
        self.assertEqual(payload.key, "connector_key")

    def test_connector_type_update_validation_rejects_empty_patch(self) -> None:
        with self.assertRaises(ValidationError):
            ConnectorTypeUpdateValidation()

    def test_connector_type_update_validation_rejects_empty_key(self) -> None:
        with self.assertRaises(ValidationError):
            ConnectorTypeUpdateValidation(key=" ")

    def test_connector_type_update_validation_rejects_empty_display_name(
        self,
    ) -> None:
        with self.assertRaises(ValidationError):
            ConnectorTypeUpdateValidation(display_name=" ")

    def test_connector_type_update_validation_rejects_invalid_adapter_kind(
        self,
    ) -> None:
        with self.assertRaises(ValidationError):
            ConnectorTypeUpdateValidation(adapter_kind="grpc")

    def test_connector_type_update_validation_rejects_empty_adapter_kind(
        self,
    ) -> None:
        with self.assertRaises(ValidationError):
            ConnectorTypeUpdateValidation(adapter_kind=" ")

    def test_connector_type_update_validation_rejects_malformed_capabilities_json(
        self,
    ) -> None:
        with self.assertRaises(ValidationError):
            ConnectorTypeUpdateValidation(capabilities_json=[])

        with self.assertRaises(ValidationError):
            ConnectorTypeUpdateValidation(
                capabilities_json={
                    "probe": {
                        "PathTemplate": "missing-leading-slash",
                    }
                }
            )

    def test_connector_instance_create_validation_requires_type_reference(self) -> None:
        connector_type_id = uuid.uuid4()

        payload = ConnectorInstanceCreateValidation(
            connector_type_id=connector_type_id,
            display_name="Connector One",
            config_json={"BaseUrl": "https://example.com"},
            secret_ref="ops_connector_default",
            status="active",
        )
        self.assertEqual(payload.connector_type_id, connector_type_id)

        payload_with_key = ConnectorInstanceCreateValidation(
            connector_type_key="http_json_default",
            display_name="Connector Two",
            config_json={"BaseUrl": "https://example.com"},
            secret_ref="ops_connector_default",
        )
        self.assertEqual(payload_with_key.connector_type_key, "http_json_default")

        with self.assertRaises(ValidationError):
            ConnectorInstanceCreateValidation(
                display_name="Connector Three",
                config_json={"BaseUrl": "https://example.com"},
                secret_ref="ops_connector_default",
            )

        with self.assertRaises(ValidationError):
            ConnectorInstanceCreateValidation(
                connector_type_key="  ",
                display_name="Connector Three",
                config_json={"BaseUrl": "https://example.com"},
                secret_ref="ops_connector_default",
            )

    def test_connector_instance_create_validation_rejects_invalid_shapes(self) -> None:
        with self.assertRaises(ValidationError):
            ConnectorInstanceCreateValidation(
                connector_type_id=uuid.uuid4(),
                connector_type_key=" ",
                display_name="Connector",
                config_json={"BaseUrl": "https://example.com"},
                secret_ref="ops_connector_default",
            )

        with self.assertRaises(ValidationError):
            ConnectorInstanceCreateValidation(
                connector_type_key="http_json_default",
                display_name=" ",
                config_json={"BaseUrl": "https://example.com"},
                secret_ref="ops_connector_default",
            )

        with self.assertRaises(ValidationError):
            ConnectorInstanceCreateValidation(
                connector_type_key="http_json_default",
                display_name="Connector",
                config_json={"BaseUrl": "https://example.com"},
                secret_ref=" ",
            )

        with self.assertRaises(ValidationError):
            ConnectorInstanceCreateValidation(
                connector_type_key="http_json_default",
                display_name="Connector",
                config_json=[],
                secret_ref="ops_connector_default",
            )

        with self.assertRaises(ValidationError):
            ConnectorInstanceCreateValidation(
                connector_type_key="http_json_default",
                display_name="Connector",
                config_json={"BaseUrl": "https://example.com"},
                secret_ref="ops_connector_default",
                retry_policy_json=[],
            )

    def test_action_payload_validations(self) -> None:
        test_connection = ConnectorInstanceTestConnectionValidation(
            row_version=2,
            trace_id=" trace-1 ",
        )
        self.assertEqual(test_connection.trace_id, "trace-1")

        invoke = ConnectorInstanceInvokeValidation(
            row_version=3,
            capability_name=" invoke_one ",
            input_json={"k": "v"},
            trace_id=" trace-2 ",
            client_action_key=" key-1 ",
        )
        self.assertEqual(invoke.capability_name, "invoke_one")
        self.assertEqual(invoke.trace_id, "trace-2")
        self.assertEqual(invoke.client_action_key, "key-1")

        with self.assertRaises(ValidationError):
            ConnectorInstanceInvokeValidation(
                row_version=3,
                capability_name=" ",
                input_json={},
            )

    def test_retry_policy_validation(self) -> None:
        default_policy = ConnectorRetryPolicyValidation()
        self.assertIsNone(default_policy.retry_status_codes)

        valid = ConnectorRetryPolicyValidation(
            timeout_seconds=10.0,
            max_retries=2,
            retry_backoff_seconds=0.5,
            retry_status_codes=[429, 500, 504],
        )
        self.assertEqual(valid.max_retries, 2)

        with self.assertRaises(ValidationError):
            ConnectorRetryPolicyValidation(retry_status_codes=[])

        with self.assertRaises(ValidationError):
            ConnectorRetryPolicyValidation(retry_status_codes=[700])

"""Validation tests for ACP Phase 1 foundation payload models."""

from pathlib import Path
from types import ModuleType
import sys
import unittest
import uuid

from pydantic import ValidationError


def _bootstrap_namespace_packages() -> None:
    root = Path(__file__).resolve().parents[1] / "mugen"

    if "mugen" not in sys.modules:
        mugen_pkg = ModuleType("mugen")
        mugen_pkg.__path__ = [str(root)]
        sys.modules["mugen"] = mugen_pkg

    if "mugen.core" not in sys.modules:
        core_pkg = ModuleType("mugen.core")
        core_pkg.__path__ = [str(root / "core")]
        sys.modules["mugen.core"] = core_pkg
        setattr(sys.modules["mugen"], "core", core_pkg)


_bootstrap_namespace_packages()

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.plugin.acp.api.validation.foundation import (
    DedupAcquireValidation,
    DedupCommitFailureValidation,
    DedupCommitSuccessValidation,
    DedupRecordCreateValidation,
    SchemaActivateVersionValidation,
    SchemaBindingCreateValidation,
    SchemaBindingUpdateValidation,
    SchemaCoerceValidation,
    SchemaDefinitionCreateValidation,
    SchemaDefinitionUpdateValidation,
    SchemaValidateValidation,
)


class TestMugenAcpValidationFoundation(unittest.TestCase):
    """Covers validation behavior for Phase 1 foundation payload schemas."""

    def test_dedup_acquire_requires_non_empty_scope_and_key(self) -> None:
        with self.assertRaises(ValidationError):
            DedupAcquireValidation(
                scope="   ",
                idempotency_key="abc",
            )

        with self.assertRaises(ValidationError):
            DedupAcquireValidation(
                scope="acp:create:Users",
                idempotency_key="   ",
            )

        payload = DedupAcquireValidation(
            scope="acp:create:Users",
            idempotency_key="e2e-key",
        )
        self.assertEqual(payload.scope, "acp:create:Users")
        self.assertEqual(payload.idempotency_key, "e2e-key")

    def test_dedup_record_create_validation(self) -> None:
        payload = DedupRecordCreateValidation(
            scope="  acp:action:Users:provision  ",
            idempotency_key="  key-1 ",
            expires_at="2099-01-01T00:00:00Z",
            status=" SUCCEEDED ",
            response_code=201,
        )
        self.assertEqual(payload.scope, "acp:action:Users:provision")
        self.assertEqual(payload.idempotency_key, "key-1")
        self.assertEqual(payload.status, "succeeded")

        with self.assertRaises(ValidationError):
            DedupRecordCreateValidation(
                scope="acp:action:Users:provision",
                idempotency_key="key-1",
                expires_at="2099-01-01T00:00:00Z",
                status="unknown",
            )

        payload_no_status = DedupRecordCreateValidation(
            scope="acp:action:Users:provision",
            idempotency_key="key-1",
            expires_at="2099-01-01T00:00:00Z",
        )
        self.assertIsNone(payload_no_status.status)

        with self.assertRaises(ValidationError):
            DedupRecordCreateValidation(
                scope="   ",
                idempotency_key="key-1",
                expires_at="2099-01-01T00:00:00Z",
            )

        with self.assertRaises(ValidationError):
            DedupRecordCreateValidation(
                scope="acp:action:Users:provision",
                idempotency_key="   ",
                expires_at="2099-01-01T00:00:00Z",
            )

    def test_schema_definition_create_validation_alias_and_status(self) -> None:
        payload = SchemaDefinitionCreateValidation(
            key="  schema-key ",
            version=1,
            SchemaJson={"type": "object"},
            status=" ACTIVE ",
        )
        self.assertEqual(payload.key, "schema-key")
        self.assertEqual(payload.status, "active")
        self.assertEqual(payload.schema_payload["type"], "object")

        payload = SchemaDefinitionCreateValidation(
            key="schema-key",
            version=1,
            SchemaJson={"type": "object"},
            schema_kind="   ",
        )
        self.assertEqual(payload.schema_kind, "json_schema")

        with self.assertRaises(ValidationError):
            SchemaDefinitionCreateValidation(
                key="   ",
                version=1,
                SchemaJson={"type": "object"},
            )

        with self.assertRaises(ValidationError):
            SchemaDefinitionCreateValidation(
                key="schema-key",
                version=1,
                SchemaJson={"type": "object"},
                status="oops",
            )

    def test_schema_definition_update_validation_rules(self) -> None:
        payload = SchemaDefinitionUpdateValidation(
            schema_kind=" json_schema ",
            status=" ACTIVE ",
        )
        self.assertEqual(payload.schema_kind, "json_schema")
        self.assertEqual(payload.status, "active")

        with self.assertRaises(ValidationError):
            SchemaDefinitionUpdateValidation(schema_kind="   ")

        with self.assertRaises(ValidationError):
            SchemaDefinitionUpdateValidation(status="invalid")

        payload = SchemaDefinitionUpdateValidation()
        self.assertIsNone(payload.status)

    def test_schema_binding_create_validation_normalizes_values(self) -> None:
        payload = SchemaBindingCreateValidation(
            schema_definition_id=uuid.uuid4(),
            target_namespace="  com.vorsocomputing.mugen.acp ",
            target_entity_set=" Users ",
            target_action="  ",
            binding_kind=" CREATE ",
        )
        self.assertEqual(payload.target_namespace, "com.vorsocomputing.mugen.acp")
        self.assertEqual(payload.target_entity_set, "Users")
        self.assertIsNone(payload.target_action)
        self.assertEqual(payload.binding_kind, "create")

        with self.assertRaises(ValidationError):
            SchemaBindingCreateValidation(
                schema_definition_id=uuid.uuid4(),
                target_namespace="   ",
                target_entity_set="Users",
                binding_kind="create",
            )

        with self.assertRaises(ValidationError):
            SchemaBindingCreateValidation(
                schema_definition_id=uuid.uuid4(),
                target_namespace="ns",
                target_entity_set="   ",
                binding_kind="create",
            )

        with self.assertRaises(ValidationError):
            SchemaBindingCreateValidation(
                schema_definition_id=uuid.uuid4(),
                target_namespace="ns",
                target_entity_set="Users",
                binding_kind="   ",
            )

    def test_schema_binding_update_validation_normalizes_action(self) -> None:
        payload = SchemaBindingUpdateValidation(target_action="   ")
        self.assertIsNone(payload.target_action)
        payload = SchemaBindingUpdateValidation()
        self.assertIsNone(payload.target_action)

    def test_schema_reference_validation_rules(self) -> None:
        with self.assertRaises(ValidationError):
            SchemaValidateValidation(payload={"Name": "x"})

        payload = SchemaValidateValidation(
            key="k1",
            version=1,
            payload={"Name": "x"},
        )
        self.assertEqual(payload.key, "k1")
        self.assertEqual(payload.version, 1)

        payload = SchemaCoerceValidation(
            schema_definition_id=uuid.uuid4(),
            payload={"Name": "x"},
        )
        self.assertIsNotNone(payload.schema_definition_id)

        with self.assertRaises(ValidationError):
            SchemaValidateValidation(
                key="k1",
                payload={"Name": "x"},
            )

    def test_commit_validation_defaults(self) -> None:
        success = DedupCommitSuccessValidation()
        failure = DedupCommitFailureValidation()
        self.assertEqual(success.response_code, 200)
        self.assertEqual(failure.response_code, 500)

    def test_schema_activate_version_key_non_empty(self) -> None:
        with self.assertRaises(ValidationError):
            SchemaActivateVersionValidation(key="   ", version=1)

        payload = SchemaActivateVersionValidation(key=" sample ", version=2)
        self.assertEqual(payload.key, "sample")

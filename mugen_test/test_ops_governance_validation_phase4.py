"""Validation tests for ops_governance phase4 payload models."""

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
from mugen.core.plugin.ops_governance.api.validation import (
    LegalHoldCreateValidation,
    LegalHoldPlaceHoldActionValidation,
    LegalHoldReleaseHoldActionValidation,
    RetentionClassCreateValidation,
    RetentionClassUpdateValidation,
    RetentionPolicyRunLifecycleValidation,
)


class TestOpsGovernanceValidationPhase4(unittest.TestCase):
    """Covers new phase4 validation branches."""

    def test_retention_class_validation(self) -> None:
        tenant_id = uuid.uuid4()
        payload = RetentionClassCreateValidation(
            tenant_id=tenant_id,
            code=" default-audit ",
            name=" Default Audit ",
            resource_type=" audit ",
            description=" keep records ",
        )
        self.assertEqual(payload.tenant_id, tenant_id)
        self.assertEqual(payload.code, " default-audit ")
        self.assertEqual(payload.resource_type, "audit_event")
        self.assertEqual(payload.retention_days, 0)
        self.assertIsNone(payload.redaction_after_days)
        self.assertEqual(payload.purge_grace_days, 30)

        with self.assertRaises(ValidationError):
            RetentionClassCreateValidation(
                tenant_id=tenant_id,
                code=" ",
                name="name",
                resource_type="audit_event",
            )
        with self.assertRaises(ValidationError):
            RetentionClassCreateValidation(
                tenant_id=tenant_id,
                code="code",
                name=" ",
                resource_type="audit_event",
            )
        with self.assertRaises(ValidationError):
            RetentionClassCreateValidation(
                tenant_id=tenant_id,
                code="code",
                name="name",
                resource_type=" ",
            )
        with self.assertRaises(ValidationError):
            RetentionClassCreateValidation(
                tenant_id=tenant_id,
                code="code",
                name="name",
                resource_type="audit_event",
                description=" ",
            )
        with self.assertRaises(ValidationError):
            RetentionClassCreateValidation(
                tenant_id=tenant_id,
                code="code",
                name="name",
                resource_type="not_supported",
            )

    def test_retention_class_update_accepts_non_negative_day_counts(self) -> None:
        payload = RetentionClassUpdateValidation.model_validate(
            {
                "RowVersion": 1,
                "RetentionDays": 365,
                "RedactionAfterDays": 90,
                "PurgeGraceDays": 30,
            }
        )

        self.assertEqual(payload.retention_days, 365)
        self.assertEqual(payload.redaction_after_days, 90)
        self.assertEqual(payload.purge_grace_days, 30)

    def test_retention_class_update_rejects_invalid_day_counts(self) -> None:
        fields = (
            "RetentionDays",
            "RedactionAfterDays",
            "PurgeGraceDays",
        )
        for field_name in fields:
            for invalid_value in (-1, 1.5, "not-an-integer"):
                with self.subTest(field=field_name, value=invalid_value):
                    with self.assertRaises(ValidationError):
                        RetentionClassUpdateValidation.model_validate(
                            {field_name: invalid_value}
                        )

    def test_legal_hold_validation(self) -> None:
        tenant_id = uuid.uuid4()
        resource_id = uuid.uuid4()

        create_payload = LegalHoldCreateValidation(
            tenant_id=tenant_id,
            resource_type="AuditEvent",
            resource_id=resource_id,
            reason="litigation",
        )
        self.assertEqual(create_payload.resource_id, resource_id)
        self.assertEqual(create_payload.resource_type, "audit_event")

        with self.assertRaises(ValidationError):
            LegalHoldCreateValidation(
                tenant_id=tenant_id,
                resource_type=" ",
                resource_id=resource_id,
                reason="ok",
            )
        with self.assertRaises(ValidationError):
            LegalHoldCreateValidation(
                tenant_id=tenant_id,
                resource_type="audit_event",
                resource_id=resource_id,
                reason=" ",
            )
        with self.assertRaises(ValidationError):
            LegalHoldCreateValidation(
                tenant_id=tenant_id,
                resource_type="other",
                resource_id=resource_id,
                reason="ok",
            )

        place_payload = LegalHoldPlaceHoldActionValidation(
            resource_type="evidence",
            resource_id=resource_id,
            reason="legal request",
        )
        self.assertEqual(place_payload.resource_type, "evidence_blob")

        with self.assertRaises(ValidationError):
            LegalHoldPlaceHoldActionValidation(
                resource_type=" ",
                resource_id=resource_id,
                reason="x",
            )
        with self.assertRaises(ValidationError):
            LegalHoldPlaceHoldActionValidation(
                resource_type="audit_event",
                resource_id=resource_id,
                reason=" ",
            )
        with self.assertRaises(ValidationError):
            LegalHoldPlaceHoldActionValidation(
                resource_type="unknown",
                resource_id=resource_id,
                reason="x",
            )

        release_payload = LegalHoldReleaseHoldActionValidation(
            row_version=4,
            reason="case closed",
        )
        self.assertEqual(release_payload.reason, "case closed")
        with self.assertRaises(ValidationError):
            LegalHoldReleaseHoldActionValidation(row_version=4, reason=" ")

    def test_retention_run_lifecycle_validation_defaults(self) -> None:
        payload = RetentionPolicyRunLifecycleValidation(row_version=2)
        self.assertFalse(payload.dry_run)
        self.assertIsNone(payload.batch_size)
        self.assertIsNone(payload.max_batches)

"""Validation tests for audit action payload models."""

from pathlib import Path
from types import ModuleType
import sys
import unittest

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
from mugen.core.plugin.audit.api.validation import (
    AuditBizTraceInspectTraceValidation,
    AuditCorrelationResolveTraceValidation,
    AuditEventRedactValidation,
    EvidenceBlobPlaceLegalHoldValidation,
    EvidenceBlobPurgeValidation,
    EvidenceBlobRegisterValidation,
    EvidenceBlobReleaseLegalHoldValidation,
    EvidenceBlobTombstoneValidation,
    EvidenceBlobVerifyHashValidation,
)


class TestAuditValidation(unittest.TestCase):
    """Covers reason validation for audit lifecycle actions."""

    def test_reason_must_be_non_empty(self) -> None:
        with self.assertRaises(ValidationError):
            AuditEventRedactValidation(
                row_version=1,
                reason="   ",
            )

        payload = AuditEventRedactValidation(
            row_version=1,
            reason="policy",
        )
        self.assertEqual(payload.reason, "policy")

    def test_correlation_trace_requires_reference(self) -> None:
        with self.assertRaises(ValidationError):
            AuditCorrelationResolveTraceValidation()

        payload = AuditCorrelationResolveTraceValidation(trace_id="  abc123  ")
        self.assertEqual(payload.trace_id, "abc123")

    def test_biz_trace_inspect_requires_reference(self) -> None:
        with self.assertRaises(ValidationError):
            AuditBizTraceInspectTraceValidation(stage="finish")

        payload = AuditBizTraceInspectTraceValidation(
            correlation_id=" corr-1 ",
            stage=" finish ",
        )
        self.assertEqual(payload.correlation_id, "corr-1")
        self.assertEqual(payload.stage, "finish")

    def test_evidence_blob_validation_models(self) -> None:
        payload = EvidenceBlobRegisterValidation(
            storage_uri=" s3://bucket/object ",
            content_hash=" abc123 ",
            hash_alg=" ",
            immutability=" immutable ",
            trace_id="trace-1",
        )
        self.assertEqual(payload.storage_uri, "s3://bucket/object")
        self.assertEqual(payload.content_hash, "abc123")
        self.assertEqual(payload.hash_alg, "sha256")
        self.assertEqual(payload.immutability, "immutable")

        with self.assertRaises(ValidationError):
            EvidenceBlobRegisterValidation(storage_uri=" ", content_hash="abc")
        with self.assertRaises(ValidationError):
            EvidenceBlobRegisterValidation(storage_uri="uri", content_hash=" ")
        with self.assertRaises(ValidationError):
            EvidenceBlobRegisterValidation(
                storage_uri="uri",
                content_hash="abc",
                immutability="invalid",
            )
        with self.assertRaises(ValidationError):
            EvidenceBlobRegisterValidation(
                storage_uri="uri",
                content_hash="abc",
                trace_id=" ",
            )
        with self.assertRaises(ValidationError):
            EvidenceBlobRegisterValidation(
                storage_uri="uri",
                content_hash="abc",
                source_plugin=" ",
            )
        with self.assertRaises(ValidationError):
            EvidenceBlobRegisterValidation(
                storage_uri="uri",
                content_hash="abc",
                subject_namespace=" ",
            )

        verify = EvidenceBlobVerifyHashValidation(
            row_version=1,
            observed_hash=" deadbeef ",
            observed_hash_alg=" ",
        )
        self.assertEqual(verify.observed_hash, "deadbeef")
        self.assertEqual(verify.observed_hash_alg, "sha256")
        self.assertEqual(
            EvidenceBlobVerifyHashValidation(
                row_version=1,
                observed_hash="deadbeef",
                observed_hash_alg="sha512",
            ).observed_hash_alg,
            "sha512",
        )
        with self.assertRaises(ValidationError):
            EvidenceBlobVerifyHashValidation(row_version=1, observed_hash=" ")

        hold = EvidenceBlobPlaceLegalHoldValidation(
            row_version=2,
            reason=" litigation ",
        )
        self.assertEqual(hold.reason, " litigation ")
        with self.assertRaises(ValidationError):
            EvidenceBlobPlaceLegalHoldValidation(row_version=2, reason=" ")

        released = EvidenceBlobReleaseLegalHoldValidation(
            row_version=3, reason=" done "
        )
        redacted = EvidenceBlobTombstoneValidation(
            row_version=4, reason="policy", purge_after_days=7
        )
        purged = EvidenceBlobPurgeValidation(row_version=5, reason="expired")
        self.assertEqual(released.reason, " done ")
        self.assertEqual(redacted.purge_after_days, 7)
        self.assertEqual(purged.reason, "expired")

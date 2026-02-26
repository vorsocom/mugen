"""Validation tests for ops_reporting Phase 5 payload extensions."""

import unittest
import uuid

from pydantic import ValidationError

from mugen.core.plugin.ops_reporting.api.validation import (
    ExportJobBuildValidation,
    ExportJobCreateValidation,
    ExportJobVerifyValidation,
    ReportSnapshotGenerateValidation,
    ReportSnapshotVerifyValidation,
)


class TestOpsReportingPhase5Validations(unittest.TestCase):
    """Covers new validation branches introduced for Phase 5."""

    def test_report_snapshot_generate_validation_branches(self) -> None:
        valid = ReportSnapshotGenerateValidation(
            row_version=1,
            trace_id="trace-1",
            signature_key_id="key-1",
            sign=True,
        )
        self.assertEqual(valid.trace_id, "trace-1")
        self.assertEqual(valid.signature_key_id, "key-1")

        with self.assertRaises(ValidationError):
            ReportSnapshotGenerateValidation(
                row_version=1,
                trace_id=" ",
            )

        with self.assertRaises(ValidationError):
            ReportSnapshotGenerateValidation(
                row_version=1,
                signature_key_id=" ",
            )

    def test_export_job_create_validation_branches(self) -> None:
        snapshot_id = uuid.uuid4()

        valid = ExportJobCreateValidation(
            export_type="report_snapshot_pack",
            spec_json={
                "ResourceRefs": {
                    "OpsReportingReportSnapshots": [str(snapshot_id)],
                },
                "Proofs": {"AuditChain": {"MaxRows": 100}},
                "ExportRef": "bundle://ref",
            },
            trace_id="trace-1",
            signature_key_id="key-1",
        )
        self.assertEqual(valid.trace_id, "trace-1")
        self.assertEqual(valid.signature_key_id, "key-1")

        with self.assertRaises(ValidationError):
            ExportJobCreateValidation(
                export_type="report_snapshot_pack",
                trace_id=" ",
                spec_json={"ResourceRefs": {"OpsReportingReportSnapshots": []}},
            )

        with self.assertRaises(ValidationError):
            ExportJobCreateValidation(
                export_type="report_snapshot_pack",
                signature_key_id=" ",
                spec_json={"ResourceRefs": {"OpsReportingReportSnapshots": []}},
            )

        with self.assertRaises(ValidationError):
            ExportJobCreateValidation(
                export_type="report_snapshot_pack",
                spec_json={"ResourceRefs": []},
            )

        with self.assertRaises(ValidationError):
            ExportJobCreateValidation(
                export_type="report_snapshot_pack",
                spec_json={"ResourceRefs": {"OpsReportingReportSnapshots": ["bad"]}},
            )

        with self.assertRaises(ValidationError):
            ExportJobCreateValidation(
                export_type="report_snapshot_pack",
                spec_json={"ResourceRefs": {"   ": [str(snapshot_id)]}},
            )

        with self.assertRaises(ValidationError):
            ExportJobCreateValidation(
                export_type="report_snapshot_pack",
                spec_json={"ResourceRefs": {"OpsReportingReportSnapshots": "bad"}},
            )

        with self.assertRaises(ValidationError):
            ExportJobCreateValidation(
                export_type="report_snapshot_pack",
                spec_json={
                    "ResourceRefs": {"OpsReportingReportSnapshots": [str(snapshot_id)]},
                    "Proofs": "bad",
                },
            )

        with self.assertRaises(ValidationError):
            ExportJobCreateValidation(
                export_type="report_snapshot_pack",
                spec_json={
                    "ResourceRefs": {"OpsReportingReportSnapshots": [str(snapshot_id)]},
                    "ExportRef": " ",
                },
            )

    def test_export_job_build_and_verify_validation_defaults(self) -> None:
        valid_build = ExportJobBuildValidation(row_version=2)
        self.assertFalse(valid_build.force)
        self.assertIsNone(valid_build.sign)

        explicit_unsigned = ExportJobBuildValidation(row_version=2, sign=False)
        self.assertFalse(explicit_unsigned.sign)

        with self.assertRaises(ValidationError):
            ExportJobBuildValidation(
                row_version=2,
                signature_key_id=" ",
            )

        snapshot_verify = ReportSnapshotVerifyValidation()
        export_verify = ExportJobVerifyValidation(require_clean=True)
        self.assertFalse(snapshot_verify.require_clean)
        self.assertTrue(export_verify.require_clean)

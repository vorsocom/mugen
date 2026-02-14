"""Additional branch tests for plugin API validation schemas."""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from mugen.core.plugin.channel_orchestration.api.validation import (
    BlockSenderActionValidation,
    EvaluateIntakeValidation,
    SetFallbackValidation,
    UnblockSenderActionValidation,
)
from mugen.core.plugin.knowledge_pack.api.validation import (
    KnowledgeEntryCreateValidation,
    KnowledgeEntryRevisionCreateValidation,
    KnowledgeScopeCreateValidation,
)
from mugen.core.plugin.ops_case.api.validation import (
    CaseAssignValidation,
    CaseLinkCreateValidation,
)
from mugen.core.plugin.ops_governance.api.validation import (
    ApplyRetentionActionValidation,
    ConsentRecordCreateValidation,
    DataHandlingRecordCreateValidation,
    DelegationGrantCreateValidation,
    EvaluatePolicyActionValidation,
    GrantDelegationActionValidation,
    PolicyDefinitionCreateValidation,
    RecordConsentActionValidation,
    RetentionPolicyCreateValidation,
    RevokeDelegationActionValidation,
    WithdrawConsentActionValidation,
)
from mugen.core.plugin.ops_metering.api.validation import (
    MeterPolicyCreateValidation,
    UsageRecordCreateValidation,
    UsageRecordRateValidation,
    UsageRecordVoidValidation,
    UsageSessionCreateValidation,
    UsageSessionPauseValidation,
    UsageSessionResumeValidation,
    UsageSessionStartValidation,
    UsageSessionStopValidation,
)
from mugen.core.plugin.ops_reporting.api.validation import (
    AggregationJobCreateValidation,
    KpiThresholdCreateValidation,
    MetricDefinitionCreateValidation,
    MetricRecomputeWindowValidation,
    MetricRunAggregationValidation,
    ReportDefinitionCreateValidation,
    ReportSnapshotArchiveValidation,
    ReportSnapshotCreateValidation,
    ReportSnapshotGenerateValidation,
    ReportSnapshotPublishValidation,
)
from mugen.core.plugin.ops_sla.api.validation import (
    SlaClockCreateValidation,
    SlaTargetCreateValidation,
)
from mugen.core.plugin.ops_vpn.api.validation import (
    VendorPerformanceEventCreateValidation,
    VendorScorecardRollupValidation,
)
from mugen.core.plugin.ops_workflow.api.validation import (
    WorkflowAdvanceValidation,
    WorkflowAssignTaskValidation,
)


class TestMugenApiValidationBranches(unittest.TestCase):
    """Covers validation error paths not reached by lifecycle happy-path tests."""

    def test_ops_vpn_validators(self) -> None:
        now = datetime.now(timezone.utc)
        with self.assertRaises(ValidationError):
            VendorScorecardRollupValidation(
                row_version=1,
                vendor_id=uuid.uuid4(),
                period_start=now,
                period_end=now - timedelta(days=1),
            )

        with self.assertRaises(ValidationError):
            VendorPerformanceEventCreateValidation(
                row_version=1,
                vendor_id=uuid.uuid4(),
                metric_type="latency",
            )

        with self.assertRaises(ValidationError):
            VendorPerformanceEventCreateValidation(
                row_version=1,
                vendor_id=uuid.uuid4(),
                metric_type="latency",
                metric_numerator=10,
            )
        with self.assertRaises(ValidationError):
            VendorPerformanceEventCreateValidation(
                row_version=1,
                vendor_id=uuid.uuid4(),
                metric_type="latency",
                normalized_score=50,
                metric_numerator=10,
            )

        valid_rollup = VendorScorecardRollupValidation(
            row_version=1,
            vendor_id=uuid.uuid4(),
            period_start=now - timedelta(days=1),
            period_end=now,
        )
        self.assertIsNotNone(valid_rollup)

        valid_event = VendorPerformanceEventCreateValidation(
            row_version=1,
            vendor_id=uuid.uuid4(),
            metric_type="latency",
            metric_numerator=10,
            metric_denominator=20,
        )
        self.assertIsNotNone(valid_event)

    def test_ops_sla_validators(self) -> None:
        tenant_id = uuid.uuid4()
        with self.assertRaises(ValidationError):
            SlaClockCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                tracked_namespace=" ",
                metric="m",
                tracked_ref="abc",
            )
        with self.assertRaises(ValidationError):
            SlaClockCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                tracked_namespace="ops",
                metric=" ",
                tracked_ref="abc",
            )
        with self.assertRaises(ValidationError):
            SlaClockCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                tracked_namespace="ops",
                metric="m",
                tracked_ref=" ",
            )
        with self.assertRaises(ValidationError):
            SlaClockCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                tracked_namespace="ops",
                metric="m",
            )

        with self.assertRaises(ValidationError):
            SlaTargetCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                policy_id=uuid.uuid4(),
                metric=" ",
                target_minutes=10,
            )
        with self.assertRaises(ValidationError):
            SlaTargetCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                policy_id=uuid.uuid4(),
                metric="m",
                target_minutes=10,
                priority=" ",
            )
        with self.assertRaises(ValidationError):
            SlaTargetCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                policy_id=uuid.uuid4(),
                metric="m",
                target_minutes=10,
                severity=" ",
            )

        valid_clock = SlaClockCreateValidation(
            row_version=1,
            tenant_id=tenant_id,
            tracked_namespace="ops",
            metric="response_time",
            tracked_id=uuid.uuid4(),
        )
        self.assertIsNotNone(valid_clock)

        valid_target = SlaTargetCreateValidation(
            row_version=1,
            tenant_id=tenant_id,
            policy_id=uuid.uuid4(),
            metric="response_time",
            target_minutes=10,
            priority="p1",
            severity="sev1",
        )
        self.assertIsNotNone(valid_target)

    def test_channel_orchestration_validators(self) -> None:
        with self.assertRaises(ValidationError):
            EvaluateIntakeValidation(row_version=1)

        with self.assertRaises(ValidationError):
            SetFallbackValidation(
                row_version=1,
                fallback_mode=" ",
            )

        with self.assertRaises(ValidationError):
            BlockSenderActionValidation(row_version=1, sender_key=" ")
        with self.assertRaises(ValidationError):
            UnblockSenderActionValidation(row_version=1, sender_key=" ")

        valid_intake = EvaluateIntakeValidation(row_version=1, intent="billing")
        self.assertIsNotNone(valid_intake)
        valid_fallback = SetFallbackValidation(row_version=1, fallback_mode="queue")
        self.assertIsNotNone(valid_fallback)
        valid_block = BlockSenderActionValidation(sender_key="sender-1")
        self.assertIsNotNone(valid_block)
        valid_unblock = UnblockSenderActionValidation(sender_key="sender-1")
        self.assertIsNotNone(valid_unblock)

    def test_ops_case_validators(self) -> None:
        with self.assertRaises(ValidationError):
            CaseAssignValidation(row_version=1)

        base_kwargs = {
            "row_version": 1,
            "tenant_id": uuid.uuid4(),
            "case_id": uuid.uuid4(),
            "link_type": "relates",
            "target_type": "ticket",
        }
        with self.assertRaises(ValidationError):
            CaseLinkCreateValidation(**{**base_kwargs, "link_type": " "})
        with self.assertRaises(ValidationError):
            CaseLinkCreateValidation(**{**base_kwargs, "target_type": " "})
        with self.assertRaises(ValidationError):
            CaseLinkCreateValidation(**{**base_kwargs, "target_ref": " "})
        with self.assertRaises(ValidationError):
            CaseLinkCreateValidation(**base_kwargs)

        valid_assign = CaseAssignValidation(row_version=1, queue_name="triage")
        self.assertIsNotNone(valid_assign)
        valid_link = CaseLinkCreateValidation(
            **{**base_kwargs, "target_ref": "TICKET-1"}
        )
        self.assertIsNotNone(valid_link)

    def test_ops_workflow_validators(self) -> None:
        with self.assertRaises(ValidationError):
            WorkflowAdvanceValidation(row_version=1)
        with self.assertRaises(ValidationError):
            WorkflowAssignTaskValidation(row_version=1)

        valid_advance = WorkflowAdvanceValidation(row_version=1, transition_key="next")
        self.assertIsNotNone(valid_advance)
        valid_assign = WorkflowAssignTaskValidation(row_version=1, queue_name="ops")
        self.assertIsNotNone(valid_assign)

    def test_knowledge_pack_validators(self) -> None:
        base_entry = {
            "row_version": 1,
            "tenant_id": uuid.uuid4(),
            "knowledge_pack_id": uuid.uuid4(),
            "knowledge_pack_version_id": uuid.uuid4(),
            "entry_key": "entry-1",
            "title": "Title",
        }
        with self.assertRaises(ValidationError):
            KnowledgeEntryCreateValidation(**{**base_entry, "entry_key": " "})
        with self.assertRaises(ValidationError):
            KnowledgeEntryCreateValidation(**{**base_entry, "title": " "})
        with self.assertRaises(ValidationError):
            KnowledgeEntryCreateValidation(**{**base_entry, "summary": " "})

        base_revision = {
            "row_version": 1,
            "tenant_id": uuid.uuid4(),
            "knowledge_entry_id": uuid.uuid4(),
            "knowledge_pack_version_id": uuid.uuid4(),
            "revision_number": 1,
        }
        with self.assertRaises(ValidationError):
            KnowledgeEntryRevisionCreateValidation(**base_revision)
        with self.assertRaises(ValidationError):
            KnowledgeEntryRevisionCreateValidation(**{**base_revision, "body": " "})
        with self.assertRaises(ValidationError):
            KnowledgeEntryRevisionCreateValidation(
                **{**base_revision, "body": " ", "body_json": {"blocks": []}}
            )
        with self.assertRaises(ValidationError):
            KnowledgeEntryRevisionCreateValidation(
                **{**base_revision, "body": "ok", "channel": " "}
            )
        with self.assertRaises(ValidationError):
            KnowledgeEntryRevisionCreateValidation(
                **{**base_revision, "body": "ok", "locale": " "}
            )
        with self.assertRaises(ValidationError):
            KnowledgeEntryRevisionCreateValidation(
                **{**base_revision, "body": "ok", "category": " "}
            )

        base_scope = {
            "row_version": 1,
            "tenant_id": uuid.uuid4(),
            "knowledge_pack_version_id": uuid.uuid4(),
            "knowledge_entry_revision_id": uuid.uuid4(),
        }
        with self.assertRaises(ValidationError):
            KnowledgeScopeCreateValidation(**{**base_scope, "channel": " "})
        with self.assertRaises(ValidationError):
            KnowledgeScopeCreateValidation(**{**base_scope, "locale": " "})
        with self.assertRaises(ValidationError):
            KnowledgeScopeCreateValidation(**{**base_scope, "category": " "})

        valid_entry = KnowledgeEntryCreateValidation(
            **{**base_entry, "entry_key": "entry", "title": "Title", "summary": "s"}
        )
        self.assertIsNotNone(valid_entry)
        valid_revision = KnowledgeEntryRevisionCreateValidation(
            **{**base_revision, "body": "markdown", "channel": "web"}
        )
        self.assertIsNotNone(valid_revision)
        valid_scope = KnowledgeScopeCreateValidation(
            **{**base_scope, "channel": "web", "locale": "en-US", "category": "faq"}
        )
        self.assertIsNotNone(valid_scope)

    def test_ops_metering_validators(self) -> None:
        tenant_id = uuid.uuid4()
        meter_def_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        with self.assertRaises(ValidationError):
            UsageSessionCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                meter_definition_id=meter_def_id,
                tracked_namespace=" ",
                tracked_id=uuid.uuid4(),
            )
        with self.assertRaises(ValidationError):
            UsageSessionCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                meter_definition_id=meter_def_id,
                tracked_namespace="ops",
                tracked_ref=" ",
            )
        with self.assertRaises(ValidationError):
            UsageSessionCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                meter_definition_id=meter_def_id,
                tracked_namespace="ops",
            )

        valid_session = UsageSessionCreateValidation(
            row_version=1,
            tenant_id=tenant_id,
            meter_definition_id=meter_def_id,
            tracked_namespace="ops",
            tracked_ref="REF-1",
        )
        self.assertIsNotNone(valid_session)

        with self.assertRaises(ValidationError):
            UsageRecordCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                meter_definition_id=meter_def_id,
                measured_minutes=0,
                measured_units=0,
                measured_tasks=0,
            )
        with self.assertRaises(ValidationError):
            UsageRecordCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                meter_definition_id=meter_def_id,
                measured_units=1,
                idempotency_key=" ",
            )
        with self.assertRaises(ValidationError):
            UsageRecordCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                meter_definition_id=meter_def_id,
                measured_tasks=1,
                external_ref=" ",
            )

        valid_record = UsageRecordCreateValidation(
            row_version=1,
            tenant_id=tenant_id,
            meter_definition_id=meter_def_id,
            occurred_at=now,
            measured_minutes=1,
        )
        self.assertIsNotNone(valid_record)

        with self.assertRaises(ValidationError):
            MeterPolicyCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                meter_definition_id=meter_def_id,
                code=" ",
                name="Policy",
            )
        with self.assertRaises(ValidationError):
            MeterPolicyCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                meter_definition_id=meter_def_id,
                code="P1",
                name=" ",
            )
        with self.assertRaises(ValidationError):
            MeterPolicyCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                meter_definition_id=meter_def_id,
                code="P1",
                name="Policy",
                description=" ",
            )
        with self.assertRaises(ValidationError):
            MeterPolicyCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                meter_definition_id=meter_def_id,
                code="P1",
                name="Policy",
                effective_from=now,
                effective_to=now - timedelta(minutes=1),
            )

        valid_policy = MeterPolicyCreateValidation(
            row_version=1,
            tenant_id=tenant_id,
            meter_definition_id=meter_def_id,
            code="P1",
            name="Policy",
            effective_from=now,
            effective_to=now + timedelta(minutes=1),
        )
        self.assertIsNotNone(valid_policy)

        open_ended_policy = MeterPolicyCreateValidation(
            row_version=1,
            tenant_id=tenant_id,
            meter_definition_id=meter_def_id,
            code="P2",
            name="Policy 2",
            effective_from=now,
        )
        self.assertIsNotNone(open_ended_policy)

        self.assertIsNotNone(UsageSessionStartValidation(row_version=1))
        self.assertIsNotNone(UsageSessionPauseValidation(row_version=1))
        self.assertIsNotNone(UsageSessionResumeValidation(row_version=1))
        self.assertIsNotNone(UsageSessionStopValidation(row_version=1))
        self.assertIsNotNone(UsageRecordRateValidation(row_version=1))
        self.assertIsNotNone(UsageRecordVoidValidation(row_version=1))

    def test_ops_reporting_validators(self) -> None:
        tenant_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        with self.assertRaises(ValidationError):
            MetricDefinitionCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code=" ",
                name="Name",
                source_table="table",
            )
        with self.assertRaises(ValidationError):
            MetricDefinitionCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code="CODE",
                name=" ",
                source_table="table",
            )
        with self.assertRaises(ValidationError):
            MetricDefinitionCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code="CODE",
                name="Name",
                source_table=" ",
            )
        with self.assertRaises(ValidationError):
            MetricDefinitionCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code="CODE",
                name="Name",
                source_table="table",
                description=" ",
            )
        with self.assertRaises(ValidationError):
            MetricDefinitionCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code="CODE",
                name="Name",
                source_table="table",
                formula_type="sum_column",
            )

        valid_metric_def = MetricDefinitionCreateValidation(
            row_version=1,
            tenant_id=tenant_id,
            code="CODE",
            name="Name",
            source_table="table",
            formula_type="sum_column",
            source_value_column="amount",
        )
        self.assertIsNotNone(valid_metric_def)
        self.assertIsNotNone(
            MetricDefinitionCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code="COUNT",
                name="Count Rows",
                source_table="table",
                formula_type="count_rows",
            )
        )

        with self.assertRaises(ValidationError):
            AggregationJobCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                metric_definition_id=uuid.uuid4(),
                window_start=now,
                window_end=now,
            )
        with self.assertRaises(ValidationError):
            AggregationJobCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                metric_definition_id=uuid.uuid4(),
                window_start=now,
                window_end=now + timedelta(minutes=5),
                scope_key=" ",
            )
        with self.assertRaises(ValidationError):
            AggregationJobCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                metric_definition_id=uuid.uuid4(),
                window_start=now,
                window_end=now + timedelta(minutes=5),
                idempotency_key=" ",
            )

        valid_job = AggregationJobCreateValidation(
            row_version=1,
            tenant_id=tenant_id,
            metric_definition_id=uuid.uuid4(),
            window_start=now,
            window_end=now + timedelta(minutes=5),
            scope_key="scope",
            idempotency_key="idem",
        )
        self.assertIsNotNone(valid_job)

        with self.assertRaises(ValidationError):
            MetricRunAggregationValidation(
                row_version=1,
                window_start=now,
            )
        with self.assertRaises(ValidationError):
            MetricRunAggregationValidation(
                row_version=1,
                window_start=now,
                window_end=now,
            )
        with self.assertRaises(ValidationError):
            MetricRunAggregationValidation(
                row_version=1,
                scope_key=" ",
            )
        self.assertIsNotNone(MetricRunAggregationValidation(row_version=1))

        with self.assertRaises(ValidationError):
            MetricRecomputeWindowValidation(
                row_version=1,
                window_start=now,
                window_end=now,
            )
        with self.assertRaises(ValidationError):
            MetricRecomputeWindowValidation(
                row_version=1,
                window_start=now,
                window_end=now + timedelta(minutes=1),
                scope_key=" ",
            )
        self.assertIsNotNone(
            MetricRecomputeWindowValidation(
                row_version=1,
                window_start=now,
                window_end=now + timedelta(minutes=1),
            )
        )

        with self.assertRaises(ValidationError):
            ReportDefinitionCreateValidation(row_version=1, code=" ", name="name")
        with self.assertRaises(ValidationError):
            ReportDefinitionCreateValidation(row_version=1, code="code", name=" ")
        with self.assertRaises(ValidationError):
            ReportDefinitionCreateValidation(
                row_version=1, code="code", name="name", description=" "
            )
        with self.assertRaises(ValidationError):
            ReportDefinitionCreateValidation(
                row_version=1,
                code="code",
                name="name",
                metric_codes=["ok", " "],
            )
        self.assertIsNotNone(
            ReportDefinitionCreateValidation(
                row_version=1,
                code="code",
                name="name",
                metric_codes=["m1", "m2"],
            )
        )
        self.assertIsNotNone(
            ReportDefinitionCreateValidation(
                row_version=1,
                code="code",
                name="name",
            )
        )

        with self.assertRaises(ValidationError):
            ReportSnapshotCreateValidation(row_version=1)
        with self.assertRaises(ValidationError):
            ReportSnapshotCreateValidation(
                row_version=1,
                metric_codes=["m1"],
                window_start=now,
            )
        with self.assertRaises(ValidationError):
            ReportSnapshotCreateValidation(
                row_version=1,
                metric_codes=["m1"],
                window_start=now,
                window_end=now,
            )
        with self.assertRaises(ValidationError):
            ReportSnapshotCreateValidation(
                row_version=1,
                metric_codes=["m1"],
                scope_key=" ",
            )
        self.assertIsNotNone(
            ReportSnapshotCreateValidation(
                row_version=1,
                metric_codes=["m1"],
                window_start=now,
                window_end=now + timedelta(minutes=1),
                scope_key="scope",
            )
        )

        with self.assertRaises(ValidationError):
            ReportSnapshotGenerateValidation(row_version=1, window_start=now)
        with self.assertRaises(ValidationError):
            ReportSnapshotGenerateValidation(
                row_version=1,
                window_start=now,
                window_end=now,
            )
        with self.assertRaises(ValidationError):
            ReportSnapshotGenerateValidation(row_version=1, scope_key=" ")
        self.assertIsNotNone(ReportSnapshotGenerateValidation(row_version=1))
        self.assertIsNotNone(ReportSnapshotPublishValidation(row_version=1))
        self.assertIsNotNone(ReportSnapshotArchiveValidation(row_version=1))

        with self.assertRaises(ValidationError):
            KpiThresholdCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                metric_definition_id=uuid.uuid4(),
                scope_key=" ",
            )
        with self.assertRaises(ValidationError):
            KpiThresholdCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                metric_definition_id=uuid.uuid4(),
                warn_low=10,
                warn_high=1,
            )
        with self.assertRaises(ValidationError):
            KpiThresholdCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                metric_definition_id=uuid.uuid4(),
                critical_low=10,
                critical_high=1,
            )
        with self.assertRaises(ValidationError):
            KpiThresholdCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                metric_definition_id=uuid.uuid4(),
                description=" ",
            )
        self.assertIsNotNone(
            KpiThresholdCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                metric_definition_id=uuid.uuid4(),
                warn_low=1,
                warn_high=10,
                critical_low=1,
                critical_high=10,
                description="ok",
            )
        )

    def test_ops_governance_validators(self) -> None:
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        other_user_id = uuid.uuid4()

        with self.assertRaises(ValidationError):
            ConsentRecordCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                subject_user_id=user_id,
                controller_namespace=" ",
                purpose="p",
                scope="s",
            )
        with self.assertRaises(ValidationError):
            ConsentRecordCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                subject_user_id=user_id,
                controller_namespace="ns",
                purpose=" ",
                scope="s",
            )
        with self.assertRaises(ValidationError):
            ConsentRecordCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                subject_user_id=user_id,
                controller_namespace="ns",
                purpose="p",
                scope=" ",
            )
        with self.assertRaises(ValidationError):
            ConsentRecordCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                subject_user_id=user_id,
                controller_namespace="ns",
                purpose="p",
                scope="s",
                legal_basis=" ",
            )
        self.assertIsNotNone(
            ConsentRecordCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                subject_user_id=user_id,
                controller_namespace="ns",
                purpose="p",
                scope="s",
                legal_basis="contract",
            )
        )

        with self.assertRaises(ValidationError):
            DelegationGrantCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                principal_user_id=user_id,
                delegate_user_id=user_id,
                scope="scope",
            )
        with self.assertRaises(ValidationError):
            DelegationGrantCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                principal_user_id=user_id,
                delegate_user_id=other_user_id,
                scope=" ",
            )
        with self.assertRaises(ValidationError):
            DelegationGrantCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                principal_user_id=user_id,
                delegate_user_id=other_user_id,
                scope="scope",
                purpose=" ",
            )
        self.assertIsNotNone(
            DelegationGrantCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                principal_user_id=user_id,
                delegate_user_id=other_user_id,
                scope="scope",
            )
        )

        with self.assertRaises(ValidationError):
            PolicyDefinitionCreateValidation(
                row_version=1, tenant_id=tenant_id, code=" ", name="n"
            )
        with self.assertRaises(ValidationError):
            PolicyDefinitionCreateValidation(
                row_version=1, tenant_id=tenant_id, code="c", name=" "
            )
        with self.assertRaises(ValidationError):
            PolicyDefinitionCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code="c",
                name="n",
                description=" ",
            )
        with self.assertRaises(ValidationError):
            PolicyDefinitionCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code="c",
                name="n",
                policy_type=" ",
            )
        with self.assertRaises(ValidationError):
            PolicyDefinitionCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code="c",
                name="n",
                rule_ref=" ",
            )
        with self.assertRaises(ValidationError):
            PolicyDefinitionCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code="c",
                name="n",
                evaluation_mode=" ",
            )
        self.assertIsNotNone(
            PolicyDefinitionCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code="c",
                name="n",
            )
        )

        with self.assertRaises(ValidationError):
            RetentionPolicyCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code=" ",
                name="n",
                target_namespace="ns",
            )
        with self.assertRaises(ValidationError):
            RetentionPolicyCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code="c",
                name=" ",
                target_namespace="ns",
            )
        with self.assertRaises(ValidationError):
            RetentionPolicyCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code="c",
                name="n",
                target_namespace=" ",
            )
        with self.assertRaises(ValidationError):
            RetentionPolicyCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code="c",
                name="n",
                target_namespace="ns",
                target_entity=" ",
            )
        with self.assertRaises(ValidationError):
            RetentionPolicyCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code="c",
                name="n",
                target_namespace="ns",
                description=" ",
            )
        with self.assertRaises(ValidationError):
            RetentionPolicyCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code="c",
                name="n",
                target_namespace="ns",
                downstream_job_ref=" ",
            )
        with self.assertRaises(ValidationError):
            RetentionPolicyCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code="c",
                name="n",
                target_namespace="ns",
                action_mode=" ",
            )
        self.assertIsNotNone(
            RetentionPolicyCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                code="c",
                name="n",
                target_namespace="ns",
            )
        )

        with self.assertRaises(ValidationError):
            DataHandlingRecordCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                subject_namespace=" ",
            )
        with self.assertRaises(ValidationError):
            DataHandlingRecordCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                subject_namespace="ns",
            )
        with self.assertRaises(ValidationError):
            DataHandlingRecordCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                subject_namespace="ns",
                subject_ref=" ",
            )
        with self.assertRaises(ValidationError):
            DataHandlingRecordCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                subject_namespace="ns",
                subject_id=uuid.uuid4(),
                subject_ref=" ",
            )
        with self.assertRaises(ValidationError):
            DataHandlingRecordCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                subject_namespace="ns",
                subject_ref="ref",
                request_type=" ",
            )
        with self.assertRaises(ValidationError):
            DataHandlingRecordCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                subject_namespace="ns",
                subject_ref="ref",
                request_status=" ",
            )
        with self.assertRaises(ValidationError):
            DataHandlingRecordCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                subject_namespace="ns",
                subject_ref="ref",
                resolution_note=" ",
            )
        with self.assertRaises(ValidationError):
            DataHandlingRecordCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                subject_namespace="ns",
                subject_ref="ref",
                evidence_ref=" ",
            )
        self.assertIsNotNone(
            DataHandlingRecordCreateValidation(
                row_version=1,
                tenant_id=tenant_id,
                subject_namespace="ns",
                subject_ref="ref",
            )
        )

        with self.assertRaises(ValidationError):
            EvaluatePolicyActionValidation(
                row_version=1,
                subject_namespace=" ",
                decision="allow",
            )
        with self.assertRaises(ValidationError):
            EvaluatePolicyActionValidation(
                row_version=1,
                subject_namespace="ns",
                decision="allow",
            )
        with self.assertRaises(ValidationError):
            EvaluatePolicyActionValidation(
                row_version=1,
                subject_namespace="ns",
                subject_ref=" ",
                decision="allow",
            )
        with self.assertRaises(ValidationError):
            EvaluatePolicyActionValidation(
                row_version=1,
                subject_namespace="ns",
                subject_id=uuid.uuid4(),
                subject_ref=" ",
                decision="allow",
            )
        with self.assertRaises(ValidationError):
            EvaluatePolicyActionValidation(
                row_version=1,
                subject_namespace="ns",
                subject_ref="ref",
                decision=" ",
            )
        with self.assertRaises(ValidationError):
            EvaluatePolicyActionValidation(
                row_version=1,
                subject_namespace="ns",
                subject_ref="ref",
                decision="allow",
                outcome=" ",
            )
        with self.assertRaises(ValidationError):
            EvaluatePolicyActionValidation(
                row_version=1,
                subject_namespace="ns",
                subject_ref="ref",
                decision="allow",
                reason=" ",
            )
        self.assertIsNotNone(
            EvaluatePolicyActionValidation(
                row_version=1,
                subject_namespace="ns",
                subject_ref="ref",
                decision="allow",
            )
        )

        with self.assertRaises(ValidationError):
            ApplyRetentionActionValidation(
                row_version=1,
                action_type=" ",
                subject_namespace="ns",
                subject_ref="ref",
            )
        with self.assertRaises(ValidationError):
            ApplyRetentionActionValidation(
                row_version=1,
                action_type="delete",
                subject_namespace=" ",
                subject_ref="ref",
            )
        with self.assertRaises(ValidationError):
            ApplyRetentionActionValidation(
                row_version=1,
                action_type="delete",
                subject_namespace="ns",
            )
        with self.assertRaises(ValidationError):
            ApplyRetentionActionValidation(
                row_version=1,
                action_type="delete",
                subject_namespace="ns",
                subject_ref=" ",
            )
        with self.assertRaises(ValidationError):
            ApplyRetentionActionValidation(
                row_version=1,
                action_type="delete",
                subject_namespace="ns",
                subject_id=uuid.uuid4(),
                subject_ref=" ",
            )
        with self.assertRaises(ValidationError):
            ApplyRetentionActionValidation(
                row_version=1,
                action_type="delete",
                subject_namespace="ns",
                subject_ref="ref",
                request_status=" ",
            )
        with self.assertRaises(ValidationError):
            ApplyRetentionActionValidation(
                row_version=1,
                action_type="delete",
                subject_namespace="ns",
                subject_ref="ref",
                note=" ",
            )
        self.assertIsNotNone(
            ApplyRetentionActionValidation(
                row_version=1,
                action_type="delete",
                subject_namespace="ns",
                subject_ref="ref",
            )
        )

        self.assertIsNotNone(
            RecordConsentActionValidation(
                row_version=1,
                subject_user_id=user_id,
                controller_namespace="ns",
                purpose="p",
                scope="s",
            )
        )
        self.assertIsNotNone(WithdrawConsentActionValidation(row_version=1))
        self.assertIsNotNone(
            GrantDelegationActionValidation(
                row_version=1,
                principal_user_id=user_id,
                delegate_user_id=other_user_id,
                scope="scope",
            )
        )
        self.assertIsNotNone(RevokeDelegationActionValidation(row_version=1))

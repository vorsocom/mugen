"""Unit tests for ops_reporting ACP contribution and runtime binding."""

import unittest

from mugen.core.plugin.acp.contract.sdk.permission import (
    GlobalRoleDef,
    PermissionTypeDef,
)
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.acp.sdk.runtime_binder import AdminRuntimeBinder
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.ops_reporting.contrib import contribute
from mugen.core.plugin.ops_reporting.service.aggregation_job import (
    AggregationJobService,
)
from mugen.core.plugin.ops_reporting.service.kpi_threshold import KpiThresholdService
from mugen.core.plugin.ops_reporting.service.metric_definition import (
    MetricDefinitionService,
)
from mugen.core.plugin.ops_reporting.service.metric_series import MetricSeriesService
from mugen.core.plugin.ops_reporting.service.report_definition import (
    ReportDefinitionService,
)
from mugen.core.plugin.ops_reporting.service.report_snapshot import (
    ReportSnapshotService,
)


class _FakeRsg:  # pylint: disable=too-few-public-methods
    def __init__(self) -> None:
        self.tables = {}

    def register_tables(self, tables) -> None:
        self.tables = dict(tables)


class TestOpsReportingContribBinding(unittest.TestCase):
    """Tests ops_reporting declarative registration and runtime materialization."""

    def test_contrib_and_runtime_binding(self) -> None:
        """Contributor should register resources, tables, schema, and services."""
        admin_ns = AdminNs("com.test.admin")
        registry = AdminRegistry(strict_permission_decls=True)

        for verb in ("read", "create", "update", "delete", "manage"):
            registry.register_permission_type(PermissionTypeDef(admin_ns.ns, verb))
        registry.register_global_role(
            GlobalRoleDef(
                namespace=admin_ns.ns,
                name="administrator",
                display_name="Administrator",
            )
        )

        contribute(
            registry,
            admin_namespace=admin_ns.ns,
            plugin_namespace="com.test.ops_reporting",
        )

        fake_rsg = _FakeRsg()
        AdminRuntimeBinder(registry=registry, rsg=fake_rsg).bind_all()
        registry.freeze()

        metric_defs = registry.get_resource("OpsReportingMetricDefinitions")
        metric_series = registry.get_resource("OpsReportingMetricSeries")
        aggregation_jobs = registry.get_resource("OpsReportingAggregationJobs")
        report_defs = registry.get_resource("OpsReportingReportDefinitions")
        snapshots = registry.get_resource("OpsReportingReportSnapshots")
        thresholds = registry.get_resource("OpsReportingKpiThresholds")

        self.assertIn("ops_reporting_metric_definition", fake_rsg.tables)
        self.assertIn("ops_reporting_metric_series", fake_rsg.tables)
        self.assertIn("ops_reporting_aggregation_job", fake_rsg.tables)
        self.assertIn("ops_reporting_report_definition", fake_rsg.tables)
        self.assertIn("ops_reporting_report_snapshot", fake_rsg.tables)
        self.assertIn("ops_reporting_kpi_threshold", fake_rsg.tables)

        self.assertIsInstance(
            registry.get_edm_service(metric_defs.service_key),
            MetricDefinitionService,
        )
        self.assertIsInstance(
            registry.get_edm_service(metric_series.service_key),
            MetricSeriesService,
        )
        self.assertIsInstance(
            registry.get_edm_service(aggregation_jobs.service_key),
            AggregationJobService,
        )
        self.assertIsInstance(
            registry.get_edm_service(report_defs.service_key),
            ReportDefinitionService,
        )
        self.assertIsInstance(
            registry.get_edm_service(snapshots.service_key),
            ReportSnapshotService,
        )
        self.assertIsInstance(
            registry.get_edm_service(thresholds.service_key),
            KpiThresholdService,
        )

        self.assertIn("run_aggregation", metric_defs.capabilities.actions)
        self.assertIn("recompute_window", metric_defs.capabilities.actions)
        self.assertIn("generate_snapshot", snapshots.capabilities.actions)
        self.assertIn("publish_snapshot", snapshots.capabilities.actions)
        self.assertIn("archive_snapshot", snapshots.capabilities.actions)

        metric_type = registry.schema.get_type("OPSREPORTING.MetricDefinition")
        self.assertEqual(metric_type.entity_set_name, "OpsReportingMetricDefinitions")

        snapshot_type = registry.schema.get_type("OPSREPORTING.ReportSnapshot")
        self.assertEqual(snapshot_type.entity_set_name, "OpsReportingReportSnapshots")

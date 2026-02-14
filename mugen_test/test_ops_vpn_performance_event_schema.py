"""Unit tests for ops_vpn performance event create schema wiring."""

import unittest

from pydantic import ValidationError

from mugen.core.plugin.ops_vpn.api.validation import (
    VendorPerformanceEventCreateValidation,
)
from mugen.core.plugin.ops_vpn.contrib import contribute
from mugen.core.plugin.acp.sdk.registry import AdminRegistry


class TestOpsVpnPerformanceEventSchema(unittest.TestCase):
    """Tests performance event create schema registration and validation."""

    def test_contrib_uses_typed_create_schema(self) -> None:
        registry = AdminRegistry(strict_permission_decls=False)
        contribute(
            registry,
            admin_namespace="com.test.admin",
            plugin_namespace="com.test.ops_vpn",
        )

        resource = registry.get_resource("OpsVpnVendorPerformanceEvents")
        self.assertIs(
            resource.crud.create_schema,
            VendorPerformanceEventCreateValidation,
        )

    def test_validation_requires_metric_payload(self) -> None:
        with self.assertRaises(ValidationError):
            VendorPerformanceEventCreateValidation.model_validate(
                {
                    "VendorId": "00000000-0000-0000-0000-000000000001",
                    "MetricType": "completion_rate",
                }
            )

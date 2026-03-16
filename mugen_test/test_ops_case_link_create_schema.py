"""Unit tests for ops_case case-link create schema wiring."""

import unittest

from pydantic import ValidationError

from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.ops_case.api.validation import CaseLinkCreateValidation
from mugen.core.plugin.ops_case.contrib import contribute


class TestOpsCaseLinkCreateSchema(unittest.TestCase):
    """Tests case-link create schema registration and validation."""

    def test_contrib_uses_typed_create_schema(self) -> None:
        registry = AdminRegistry(strict_permission_decls=False)
        contribute(
            registry,
            admin_namespace="com.test.admin",
            plugin_namespace="com.test.ops_case",
        )

        resource = registry.get_resource("OpsCaseLinks")
        self.assertIs(resource.crud.create_schema, CaseLinkCreateValidation)

    def test_validation_requires_target_reference(self) -> None:
        with self.assertRaises(ValidationError):
            CaseLinkCreateValidation.model_validate(
                {
                    "TenantId": "00000000-0000-0000-0000-0000000000aa",
                    "CaseId": "00000000-0000-0000-0000-000000000001",
                    "LinkType": "invoice",
                    "TargetType": "billing.invoice",
                }
            )

    def test_validation_accepts_target_ref(self) -> None:
        validated = CaseLinkCreateValidation.model_validate(
            {
                "TenantId": "00000000-0000-0000-0000-0000000000aa",
                "CaseId": "00000000-0000-0000-0000-000000000001",
                "LinkType": "invoice",
                "TargetType": "billing.invoice",
                "TargetRef": "INV-1001",
            }
        )
        self.assertEqual(validated.target_ref, "INV-1001")

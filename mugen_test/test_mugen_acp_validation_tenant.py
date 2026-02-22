"""Tests tenant payload validators used by ACP contrib wiring."""

from __future__ import annotations

import unittest
import uuid

from pydantic import ValidationError

from mugen.core.plugin.acp.api.validation.tenant import (
    TenantDomainCreateValidation,
    TenantDomainUpdateValidation,
)


class TestMugenAcpValidationTenant(unittest.TestCase):
    """Covers branch paths in tenant validation helpers."""

    def test_domain_validators_strip_and_reject_empty_values(self) -> None:
        created = TenantDomainCreateValidation(
            tenant_id=uuid.uuid4(),
            domain="  app.example.com  ",
            is_primary=True,
        )
        self.assertEqual(created.domain, "app.example.com")

        updated = TenantDomainUpdateValidation(domain="  login.example.com  ")
        self.assertEqual(updated.domain, "login.example.com")

        updated_none = TenantDomainUpdateValidation(domain=None)
        self.assertIsNone(updated_none.domain)

        with self.assertRaises(ValidationError):
            TenantDomainCreateValidation(tenant_id=uuid.uuid4(), domain="   ")

        with self.assertRaises(ValidationError):
            TenantDomainUpdateValidation(domain="   ")

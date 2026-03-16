"""Unit tests for ACP JWT/resource contract helpers."""

from __future__ import annotations

import unittest

from mugen.core.plugin.acp.contract.service.jwt import JwtVerifyProfile
from mugen.core.plugin.acp.contract.sdk.resource import AdminCapabilities


class TestMugenAcpContractJwtAndResource(unittest.TestCase):
    """Covers profile-derived JWT requirements and capability mapping."""

    def test_jwt_verify_profile_properties(self) -> None:
        self.assertFalse(JwtVerifyProfile.GENERIC.require_issuer)
        self.assertFalse(JwtVerifyProfile.GENERIC.require_audience)
        self.assertIsNone(JwtVerifyProfile.GENERIC.enforced_type)
        self.assertEqual(
            JwtVerifyProfile.GENERIC.required_claims,
            {"exp", "iat", "nbf"},
        )

        self.assertTrue(JwtVerifyProfile.PRINCIPAL.require_issuer)
        self.assertTrue(JwtVerifyProfile.PRINCIPAL.require_audience)
        self.assertIsNone(JwtVerifyProfile.PRINCIPAL.enforced_type)
        self.assertEqual(
            JwtVerifyProfile.PRINCIPAL.required_claims,
            {"exp", "iat", "nbf", "sub"},
        )

        self.assertEqual(JwtVerifyProfile.ACCESS.enforced_type, "access")
        self.assertEqual(JwtVerifyProfile.REFRESH.enforced_type, "refresh")
        self.assertEqual(
            JwtVerifyProfile.ACCESS.required_claims,
            {"exp", "iat", "nbf", "sub", "jti", "type", "token_version"},
        )
        self.assertEqual(
            JwtVerifyProfile.REFRESH.required_claims,
            {"exp", "iat", "nbf", "sub", "jti", "type", "token_version"},
        )

    def test_admin_capabilities_op_allowed(self) -> None:
        caps = AdminCapabilities(
            allow_read=True,
            allow_create=True,
            allow_update=False,
            allow_delete=False,
            allow_manage=True,
        )
        self.assertTrue(caps.op_allowed("read"))
        self.assertTrue(caps.op_allowed("create"))
        self.assertFalse(caps.op_allowed("update"))
        self.assertFalse(caps.op_allowed("delete"))
        self.assertTrue(caps.op_allowed("manage"))
        self.assertFalse(caps.op_allowed("unknown"))

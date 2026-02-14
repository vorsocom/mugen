"""Unit tests for mugen.core.plugin.acp.utility.ns.AdminNs."""

from __future__ import annotations

import unittest

from mugen.core.plugin.acp.utility.ns import AdminNs


class TestMugenAcpAdminNs(unittest.TestCase):
    """Covers AdminNs normalization and validation branches."""

    def test_happy_path_key_obj_verb_and_perms(self) -> None:
        admin_ns = AdminNs(" Com.Test.Admin ")
        self.assertEqual(admin_ns.ns, "com.test.admin")
        self.assertEqual(admin_ns.key("read"), "com.test.admin:read")
        self.assertEqual(admin_ns.obj("user"), "com.test.admin:user")
        self.assertEqual(admin_ns.verb("manage"), "com.test.admin:manage")

        perms = admin_ns.perms("user")
        self.assertEqual(perms.permission_object, "com.test.admin:user")
        self.assertEqual(perms.read, "com.test.admin:read")
        self.assertEqual(perms.create, "com.test.admin:create")
        self.assertEqual(perms.update, "com.test.admin:update")
        self.assertEqual(perms.delete, "com.test.admin:delete")
        self.assertEqual(perms.manage, "com.test.admin:manage")

    def test_validation_errors(self) -> None:
        with self.assertRaises(ValueError):
            AdminNs("   ")
        with self.assertRaises(ValueError):
            AdminNs("com:test")

        admin_ns = AdminNs("com.test.admin")
        with self.assertRaises(ValueError):
            admin_ns.key("  ")
        with self.assertRaises(ValueError):
            admin_ns.key("bad:name")

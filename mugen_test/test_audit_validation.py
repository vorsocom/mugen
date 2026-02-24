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
    AuditEventRedactValidation,
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

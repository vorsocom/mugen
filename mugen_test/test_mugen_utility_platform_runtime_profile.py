"""Unit tests for mugen.core.utility.platform_runtime_profile."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mugen.core.utility import platform_runtime_profile as profile_mod


class TestPlatformRuntimeProfile(unittest.TestCase):
    """Covers runtime config namespace conversion helpers."""

    def test_build_config_namespace_requires_mapping(self) -> None:
        with self.assertRaisesRegex(TypeError, "Configuration root must be a mapping"):
            profile_mod.build_config_namespace([])  # type: ignore[arg-type]

    def test_build_config_namespace_requires_namespace_result(self) -> None:
        with patch.object(profile_mod, "to_namespace", return_value=[]):
            with self.assertRaisesRegex(
                TypeError,
                "Configuration namespace conversion failed",
            ):
                profile_mod.build_config_namespace({"line": {}})

    def test_build_config_namespace_returns_namespace_with_raw_dict(self) -> None:
        config = {"line": {"webhook": {"dedupe_ttl_seconds": 86400}}}

        converted = profile_mod.build_config_namespace(config)

        self.assertIsInstance(converted, SimpleNamespace)
        self.assertEqual(converted.line.webhook.dedupe_ttl_seconds, 86400)
        self.assertEqual(converted.dict, config)

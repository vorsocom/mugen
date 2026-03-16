"""Unit tests for strict runtime bootstrap contract parsing."""

from __future__ import annotations

import copy
import unittest

from mugen.core.contract.runtime_bootstrap import parse_runtime_bootstrap_settings


def _valid_runtime_config() -> dict:
    return {
        "mugen": {
            "platforms": ["web"],
            "runtime": {
                "profile": "platform_full",
                "provider_readiness_timeout_seconds": 15.0,
                "provider_shutdown_timeout_seconds": 10.0,
                "shutdown_timeout_seconds": 60.0,
                "phase_b": {
                    "startup_timeout_seconds": 30.0,
                    "readiness_grace_seconds": 1.5,
                    "critical_platforms": ["web"],
                    "degrade_on_critical_exit": True,
                },
            },
        }
    }


class TestMugenRuntimeBootstrapContract(unittest.TestCase):
    """Covers strict runtime bootstrap timeout/profile parsing branches."""

    def test_parse_runtime_bootstrap_settings_reads_required_controls(self) -> None:
        settings = parse_runtime_bootstrap_settings(_valid_runtime_config())
        self.assertEqual(settings.profile, "platform_full")
        self.assertEqual(settings.active_platforms, ["web"])
        self.assertEqual(settings.critical_platforms, ["web"])
        self.assertEqual(settings.readiness_grace_seconds, 1.5)
        self.assertTrue(settings.degrade_on_critical_exit)
        self.assertEqual(settings.startup_timeout_seconds, 30.0)
        self.assertEqual(settings.provider_readiness_timeout_seconds, 15.0)
        self.assertEqual(settings.provider_shutdown_timeout_seconds, 10.0)
        self.assertEqual(settings.shutdown_timeout_seconds, 60.0)

    def test_parse_runtime_bootstrap_settings_falls_back_critical_platforms(self) -> None:
        config = _valid_runtime_config()
        config["mugen"]["runtime"]["phase_b"]["critical_platforms"] = []
        settings = parse_runtime_bootstrap_settings(config)
        self.assertEqual(settings.critical_platforms, ["web"])

    def test_parse_runtime_bootstrap_settings_rejects_missing_required_fields(self) -> None:
        missing_cases = (
            ("profile", "profile"),
            ("provider_readiness_timeout_seconds", "provider_readiness_timeout_seconds"),
            ("provider_shutdown_timeout_seconds", "provider_shutdown_timeout_seconds"),
            ("shutdown_timeout_seconds", "shutdown_timeout_seconds"),
        )
        for key, expected_message in missing_cases:
            config = _valid_runtime_config()
            del config["mugen"]["runtime"][key]
            with self.subTest(key=key):
                with self.assertRaisesRegex(RuntimeError, expected_message):
                    parse_runtime_bootstrap_settings(config)

        config = _valid_runtime_config()
        del config["mugen"]["runtime"]["phase_b"]["startup_timeout_seconds"]
        with self.assertRaisesRegex(RuntimeError, "startup_timeout_seconds"):
            parse_runtime_bootstrap_settings(config)

    def test_parse_runtime_bootstrap_settings_rejects_invalid_required_values(self) -> None:
        invalid_cases = (
            ("profile", "legacy"),
            ("provider_readiness_timeout_seconds", 0),
            ("provider_shutdown_timeout_seconds", "bad"),
            ("shutdown_timeout_seconds", 0),
        )
        for key, invalid_value in invalid_cases:
            config = _valid_runtime_config()
            config["mugen"]["runtime"][key] = invalid_value
            with self.subTest(key=key):
                with self.assertRaises(RuntimeError):
                    parse_runtime_bootstrap_settings(config)

        config = _valid_runtime_config()
        config["mugen"]["runtime"]["phase_b"]["startup_timeout_seconds"] = "bad"
        with self.assertRaisesRegex(RuntimeError, "startup_timeout_seconds"):
            parse_runtime_bootstrap_settings(config)

    def test_parse_runtime_bootstrap_settings_accepts_namespace_shapes(self) -> None:
        config = _valid_runtime_config()
        settings = parse_runtime_bootstrap_settings(copy.deepcopy(config))
        self.assertEqual(settings.profile, "platform_full")

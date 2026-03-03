"""Unit tests for runtime bootstrap contract parsing."""

from __future__ import annotations

import unittest

from mugen.core.runtime.bootstrap_contract import parse_runtime_bootstrap_settings


class TestMugenRuntimeBootstrapContract(unittest.TestCase):
    """Covers runtime bootstrap timeout/profile parsing branches."""

    def test_parse_runtime_bootstrap_settings_reads_required_shutdown_timeouts(self) -> None:
        settings = parse_runtime_bootstrap_settings(
            {
                "mugen": {
                    "platforms": ["web"],
                    "runtime": {
                        "profile": "platform_full",
                        "provider_shutdown_timeout_seconds": "10.5",
                        "shutdown_timeout_seconds": 60,
                    },
                }
            },
            require_profile=True,
            require_startup_timeout_seconds=False,
            require_provider_readiness_timeout_seconds=False,
            require_provider_shutdown_timeout_seconds=True,
            require_shutdown_timeout_seconds=True,
        )
        self.assertEqual(settings.provider_shutdown_timeout_seconds, 10.5)
        self.assertEqual(settings.shutdown_timeout_seconds, 60.0)

    def test_parse_runtime_bootstrap_settings_defaults_optional_shutdown_timeouts(self) -> None:
        settings = parse_runtime_bootstrap_settings(
            {"mugen": {"runtime": {"profile": "platform_full"}, "platforms": []}},
            require_profile=True,
            require_startup_timeout_seconds=False,
            require_provider_readiness_timeout_seconds=False,
        )
        self.assertIsNone(settings.provider_shutdown_timeout_seconds)
        self.assertIsNone(settings.shutdown_timeout_seconds)

    def test_parse_runtime_bootstrap_settings_rejects_missing_required_shutdown_timeouts(
        self,
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "provider_shutdown_timeout_seconds"):
            parse_runtime_bootstrap_settings(
                {"mugen": {"runtime": {"profile": "platform_full"}, "platforms": []}},
                require_profile=True,
                require_startup_timeout_seconds=False,
                require_provider_readiness_timeout_seconds=False,
                require_provider_shutdown_timeout_seconds=True,
            )

        with self.assertRaisesRegex(RuntimeError, "shutdown_timeout_seconds"):
            parse_runtime_bootstrap_settings(
                {
                    "mugen": {
                        "runtime": {
                            "profile": "platform_full",
                            "provider_shutdown_timeout_seconds": 10,
                        },
                        "platforms": [],
                    }
                },
                require_profile=True,
                require_startup_timeout_seconds=False,
                require_provider_readiness_timeout_seconds=False,
                require_provider_shutdown_timeout_seconds=True,
                require_shutdown_timeout_seconds=True,
            )

    def test_parse_runtime_bootstrap_settings_rejects_invalid_shutdown_timeouts(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "provider_shutdown_timeout_seconds"):
            parse_runtime_bootstrap_settings(
                {
                    "mugen": {
                        "runtime": {
                            "profile": "platform_full",
                            "provider_shutdown_timeout_seconds": "bad",
                        }
                    }
                },
                require_profile=True,
                require_startup_timeout_seconds=False,
                require_provider_readiness_timeout_seconds=False,
            )

        with self.assertRaisesRegex(RuntimeError, "shutdown_timeout_seconds"):
            parse_runtime_bootstrap_settings(
                {
                    "mugen": {
                        "runtime": {
                            "profile": "platform_full",
                            "shutdown_timeout_seconds": 0,
                        }
                    }
                },
                require_profile=True,
                require_startup_timeout_seconds=False,
                require_provider_readiness_timeout_seconds=False,
            )

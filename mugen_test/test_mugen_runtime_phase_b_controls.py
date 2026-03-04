"""Unit tests for phase-B runtime control parsing helpers."""

from types import SimpleNamespace
import unittest

from mugen.core.runtime import phase_b_controls as controls


def _runtime_config(
    *,
    platforms: list[str] | None = None,
    phase_b: object = None,
    provider_shutdown_timeout_seconds: object = 10.0,
) -> SimpleNamespace:
    if platforms is None:
        platforms = []
    if phase_b is None:
        phase_b = SimpleNamespace(startup_timeout_seconds=30.0)
    return SimpleNamespace(
        mugen=SimpleNamespace(
            platforms=platforms,
            runtime=SimpleNamespace(
                profile="platform_full",
                provider_readiness_timeout_seconds=15.0,
                provider_shutdown_timeout_seconds=provider_shutdown_timeout_seconds,
                shutdown_timeout_seconds=60.0,
                phase_b=phase_b,
            ),
        )
    )


class TestMugenRuntimePhaseBControls(unittest.TestCase):
    """Covers runtime control parsing and startup-timeout validation."""

    def test_resolve_runtime_controls_prefers_explicit_critical_list(self) -> None:
        config = _runtime_config(
            platforms=["matrix", "web"],
            phase_b=SimpleNamespace(
                readiness_grace_seconds="2.5",
                startup_timeout_seconds=30.0,
                critical_platforms=[" WEB ", "matrix", "web"],
                degrade_on_critical_exit="off",
            ),
        )

        grace, critical, degrade = controls.resolve_phase_b_runtime_controls(config)
        self.assertEqual(grace, 2.5)
        self.assertEqual(critical, ["web", "matrix"])
        self.assertFalse(degrade)

    def test_parse_nonnegative_float_and_normalize_platform_list_helpers(self) -> None:
        self.assertEqual(
            controls.parse_nonnegative_float("2.5", default=0.0),
            2.5,
        )
        self.assertEqual(
            controls.parse_nonnegative_float("bad", default=1.0),
            1.0,
        )
        self.assertEqual(
            controls.parse_nonnegative_float(float("inf"), default=1.5),
            1.5,
        )
        self.assertEqual(
            controls.normalize_platform_list([" web ", "", "web", "matrix"]),
            ["web", "matrix"],
        )

    def test_resolve_runtime_controls_falls_back_to_active_platforms(self) -> None:
        config = _runtime_config(
            platforms=[" web ", "", "matrix"],
            phase_b=SimpleNamespace(
                readiness_grace_seconds=0,
                startup_timeout_seconds=30.0,
                critical_platforms=None,
                degrade_on_critical_exit=object(),
            ),
        )

        grace, critical, degrade = controls.resolve_phase_b_runtime_controls(config)
        self.assertEqual(grace, 0.0)
        self.assertEqual(critical, ["web", "matrix"])
        self.assertTrue(degrade)

        config.mugen.runtime.phase_b.readiness_grace_seconds = -1
        with self.assertRaisesRegex(RuntimeError, "readiness_grace_seconds"):
            controls.resolve_phase_b_runtime_controls(config)

    def test_resolve_startup_timeout_requires_phase_b_key(self) -> None:
        with self.assertRaises(RuntimeError):
            controls.resolve_phase_b_startup_timeout_seconds(None)

        config = SimpleNamespace(
            mugen=SimpleNamespace(
                runtime=SimpleNamespace(
                    profile="platform_full",
                    provider_readiness_timeout_seconds=15.0,
                    provider_shutdown_timeout_seconds=10.0,
                    shutdown_timeout_seconds=60.0,
                    phase_b=None,
                )
            )
        )
        with self.assertRaises(RuntimeError):
            controls.resolve_phase_b_startup_timeout_seconds(config)

    def test_resolve_startup_timeout_rejects_invalid_and_non_positive_values(
        self,
    ) -> None:
        config = _runtime_config(
            phase_b=SimpleNamespace(startup_timeout_seconds="not-a-number"),
        )
        with self.assertRaises(RuntimeError):
            controls.resolve_phase_b_startup_timeout_seconds(config)

        config.mugen.runtime.phase_b.startup_timeout_seconds = 0
        with self.assertRaises(RuntimeError):
            controls.resolve_phase_b_startup_timeout_seconds(config)

        config.mugen.runtime.phase_b.startup_timeout_seconds = -1
        with self.assertRaises(RuntimeError):
            controls.resolve_phase_b_startup_timeout_seconds(config)

    def test_resolve_startup_timeout_accepts_positive_numeric_value(self) -> None:
        config = _runtime_config(
            phase_b=SimpleNamespace(startup_timeout_seconds="15.25"),
        )
        self.assertEqual(
            controls.resolve_phase_b_startup_timeout_seconds(config), 15.25
        )

    def test_resolve_startup_failure_cancel_timeout_prefers_provider_shutdown_timeout(
        self,
    ) -> None:
        config = _runtime_config(
            phase_b=SimpleNamespace(startup_timeout_seconds=30.0),
            provider_shutdown_timeout_seconds="3.5",
        )

        timeout_seconds = (
            controls.resolve_phase_b_startup_failure_cancel_timeout_seconds(config)
        )
        self.assertEqual(timeout_seconds, 3.5)

    def test_resolve_startup_failure_cancel_timeout_requires_config_value(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "provider_shutdown_timeout_seconds",
        ):
            controls.resolve_phase_b_startup_failure_cancel_timeout_seconds(
                _runtime_config(provider_shutdown_timeout_seconds=None)
            )

        config = _runtime_config(
            phase_b=SimpleNamespace(startup_timeout_seconds=30.0),
            provider_shutdown_timeout_seconds="bad",
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "provider_shutdown_timeout_seconds",
        ):
            controls.resolve_phase_b_startup_failure_cancel_timeout_seconds(config)

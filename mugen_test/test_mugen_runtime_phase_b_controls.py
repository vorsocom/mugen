"""Unit tests for phase-B runtime control parsing helpers."""

from types import SimpleNamespace
import unittest

from mugen.core.runtime import phase_b_controls as controls


class TestMugenRuntimePhaseBControls(unittest.TestCase):
    """Covers runtime control parsing and startup-timeout validation."""

    def test_resolve_runtime_controls_prefers_explicit_critical_list(self) -> None:
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                platforms=["matrix", "web"],
                runtime=SimpleNamespace(
                    phase_b=SimpleNamespace(
                        readiness_grace_seconds="2.5",
                        critical_platforms=[" WEB ", "matrix", "web"],
                        degrade_on_critical_exit="off",
                    )
                ),
            )
        )

        grace, critical, degrade = controls.resolve_phase_b_runtime_controls(config)
        self.assertEqual(grace, 2.5)
        self.assertEqual(critical, ["web", "matrix"])
        self.assertFalse(degrade)

    def test_resolve_runtime_controls_falls_back_to_active_platforms(self) -> None:
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                platforms=[" web ", "", "matrix"],
                runtime=SimpleNamespace(
                    phase_b=SimpleNamespace(
                        readiness_grace_seconds=-1,
                        critical_platforms=None,
                        degrade_on_critical_exit=object(),
                    )
                ),
            )
        )

        grace, critical, degrade = controls.resolve_phase_b_runtime_controls(config)
        self.assertEqual(grace, 0.0)
        self.assertEqual(critical, ["web", "matrix"])
        self.assertTrue(degrade)

    def test_resolve_startup_timeout_requires_phase_b_key(self) -> None:
        with self.assertRaises(RuntimeError):
            controls.resolve_phase_b_startup_timeout_seconds(None)

        config = SimpleNamespace(
            mugen=SimpleNamespace(runtime=SimpleNamespace(phase_b=None))
        )
        with self.assertRaises(RuntimeError):
            controls.resolve_phase_b_startup_timeout_seconds(config)

    def test_resolve_startup_timeout_rejects_invalid_and_non_positive_values(
        self,
    ) -> None:
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                runtime=SimpleNamespace(
                    phase_b=SimpleNamespace(startup_timeout_seconds="not-a-number")
                )
            )
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
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                runtime=SimpleNamespace(
                    phase_b=SimpleNamespace(startup_timeout_seconds="15.25")
                )
            )
        )
        self.assertEqual(
            controls.resolve_phase_b_startup_timeout_seconds(config), 15.25
        )

    def test_resolve_startup_failure_cancel_timeout_prefers_provider_shutdown_timeout(
        self,
    ) -> None:
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                runtime=SimpleNamespace(provider_shutdown_timeout_seconds="3.5")
            )
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
            controls.resolve_phase_b_startup_failure_cancel_timeout_seconds(object())

        config = SimpleNamespace(
            mugen=SimpleNamespace(
                runtime=SimpleNamespace(provider_shutdown_timeout_seconds="bad")
            )
        )
        with self.assertRaisesRegex(
            RuntimeError,
            "provider_shutdown_timeout_seconds",
        ):
            controls.resolve_phase_b_startup_failure_cancel_timeout_seconds(config)

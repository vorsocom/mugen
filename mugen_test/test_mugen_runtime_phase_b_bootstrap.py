"""Unit tests for phase-B bootstrap plan coordinator helpers."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from mugen.bootstrap_state import (
    PHASE_B_ERROR_KEY,
    PHASE_B_STARTED_AT_KEY,
    PHASE_B_STATUS_KEY,
    PHASE_STATUS_STARTING,
)
from mugen.core.runtime import phase_b_bootstrap as bootstrap


class TestMugenRuntimePhaseBBootstrap(unittest.TestCase):
    """Covers shared phase-B startup-plan build/apply behavior."""

    def _config(self, *, startup_timeout_seconds: object = 30.0) -> SimpleNamespace:
        return SimpleNamespace(
            mugen=SimpleNamespace(
                platforms=["web"],
                runtime=SimpleNamespace(
                    phase_b=SimpleNamespace(
                        readiness_grace_seconds="1.5",
                        startup_timeout_seconds=startup_timeout_seconds,
                    )
                ),
            )
        )

    def test_build_plan_includes_timeout_when_requested(self) -> None:
        seen: dict[str, object] = {}

        def _validate_phase_b_runtime_config(*, config, bootstrap_state, logger):
            seen["config"] = config
            seen["bootstrap_state"] = bootstrap_state
            seen["logger"] = logger
            return ["web"], ["web"], True

        def _validate_web_relational_runtime_config(*, config, active_platforms):
            seen["web_config"] = config
            seen["active_platforms"] = list(active_platforms)

        state: dict = {}
        logger = object()
        config = self._config(startup_timeout_seconds=42)
        plan = bootstrap.build_phase_b_startup_plan(
            config=config,
            bootstrap_state=state,
            logger=logger,
            validate_phase_b_runtime_config=_validate_phase_b_runtime_config,
            validate_web_relational_runtime_config=_validate_web_relational_runtime_config,
            include_startup_timeout=True,
        )

        self.assertEqual(plan.active_platforms, ["web"])
        self.assertEqual(plan.critical_platforms, ["web"])
        self.assertTrue(plan.degrade_on_critical_exit)
        self.assertEqual(plan.readiness_grace_seconds, 1.5)
        self.assertEqual(plan.startup_timeout_seconds, 42.0)
        self.assertIs(seen["config"], config)
        self.assertIs(seen["bootstrap_state"], state)
        self.assertIs(seen["logger"], logger)
        self.assertIs(seen["web_config"], config)
        self.assertEqual(seen["active_platforms"], ["web"])

    def test_build_plan_skips_timeout_when_not_requested(self) -> None:
        plan = bootstrap.build_phase_b_startup_plan(
            config=self._config(startup_timeout_seconds="invalid"),
            bootstrap_state={},
            logger=None,
            validate_phase_b_runtime_config=lambda **_: (["matrix"], ["matrix"], False),
            validate_web_relational_runtime_config=lambda **_: None,
            include_startup_timeout=False,
        )

        self.assertEqual(plan.active_platforms, ["matrix"])
        self.assertEqual(plan.critical_platforms, ["matrix"])
        self.assertFalse(plan.degrade_on_critical_exit)
        self.assertEqual(plan.readiness_grace_seconds, 1.5)
        self.assertIsNone(plan.startup_timeout_seconds)

    def test_apply_startup_state_sets_controls_and_started_at_when_reset_enabled(
        self,
    ) -> None:
        state: dict = {}
        plan = bootstrap.PhaseBStartupPlan(
            active_platforms=["web"],
            critical_platforms=["web"],
            degrade_on_critical_exit=True,
            readiness_grace_seconds=0.25,
            startup_timeout_seconds=30.0,
        )

        bootstrap.apply_phase_b_startup_state(
            state,
            plan=plan,
            reset_started_at=True,
        )

        self.assertEqual(state[bootstrap.PHASE_B_READINESS_GRACE_KEY], 0.25)
        self.assertEqual(state[bootstrap.PHASE_B_CRITICAL_PLATFORMS_KEY], ["web"])
        self.assertTrue(state[bootstrap.PHASE_B_DEGRADE_ON_CRITICAL_EXIT_KEY])
        self.assertEqual(state[bootstrap.PHASE_B_STARTUP_TIMEOUT_KEY], 30.0)
        self.assertEqual(state[PHASE_B_STATUS_KEY], PHASE_STATUS_STARTING)
        self.assertIsNone(state[PHASE_B_ERROR_KEY])
        self.assertIsInstance(state[PHASE_B_STARTED_AT_KEY], float)

    def test_apply_startup_state_preserves_started_at_when_reset_disabled(self) -> None:
        state = {PHASE_B_STARTED_AT_KEY: 123.456}
        plan = bootstrap.PhaseBStartupPlan(
            active_platforms=["web"],
            critical_platforms=["web"],
            degrade_on_critical_exit=True,
            readiness_grace_seconds=0.0,
            startup_timeout_seconds=None,
        )

        bootstrap.apply_phase_b_startup_state(
            state,
            plan=plan,
            reset_started_at=False,
        )

        self.assertEqual(state[PHASE_B_STARTED_AT_KEY], 123.456)
        self.assertNotIn(bootstrap.PHASE_B_STARTUP_TIMEOUT_KEY, state)


if __name__ == "__main__":
    unittest.main()

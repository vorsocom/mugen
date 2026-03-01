"""Unit coverage for phase-B startup coordinator edge branches."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from mugen.core.runtime import phase_b_coordinator
from mugen.core.runtime.phase_b_bootstrap import PhaseBStartupPlan


class TestPhaseBCoordinator(unittest.TestCase):
    def test_build_startup_plan_requires_timeout(self) -> None:
        startup_plan = PhaseBStartupPlan(
            active_platforms=[],
            critical_platforms=[],
            degrade_on_critical_exit=True,
            readiness_grace_seconds=0.0,
            startup_timeout_seconds=None,
        )
        with patch.object(
            phase_b_coordinator,
            "build_phase_b_startup_plan",
            return_value=startup_plan,
        ):
            with self.assertRaises(RuntimeError):
                phase_b_coordinator._build_startup_plan(  # pylint: disable=protected-access
                    config=object(),
                    bootstrap_state={},
                    logger=object(),
                    validate_phase_b_runtime_config=lambda **_kwargs: ([], [], True),
                    validate_web_relational_runtime_config=lambda **_kwargs: None,
                )

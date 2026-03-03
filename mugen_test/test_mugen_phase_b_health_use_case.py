"""Unit tests for phase-B health use-case logic."""

from __future__ import annotations

import unittest

from mugen.core.domain.use_case import phase_b_health as phase_b_health_mod
from mugen.core.domain.use_case.phase_b_health import (
    PHASE_STATUS_DEGRADED,
    PHASE_STATUS_HEALTHY,
    PHASE_STATUS_STARTING,
    PhaseBHealthInput,
    evaluate_phase_b_health,
)


class TestPhaseBHealthUseCase(unittest.TestCase):
    """Validate pure runtime/readiness health evaluation behavior."""

    def test_reported_phase_b_degraded_remains_degraded(self) -> None:
        result = evaluate_phase_b_health(
            PhaseBHealthInput(
                platform_statuses={"web": PHASE_STATUS_HEALTHY},
                platform_errors={"web": None},
                critical_platforms=["web"],
                degrade_on_critical_exit=True,
                shutdown_requested=False,
                phase_b_status=PHASE_STATUS_DEGRADED,
                phase_b_error="phase_b task failed",
                phase_b_started_at=0.0,
                readiness_grace_seconds=0.0,
            )
        )

        self.assertEqual(result.phase_b_status, PHASE_STATUS_DEGRADED)
        self.assertEqual(result.phase_b_error, "phase_b task failed")
        self.assertEqual(result.reasons, {"phase_b": "phase_b task failed"})

    def test_reported_phase_b_error_remains_degraded(self) -> None:
        result = evaluate_phase_b_health(
            PhaseBHealthInput(
                platform_statuses={"web": PHASE_STATUS_HEALTHY},
                platform_errors={"web": None},
                critical_platforms=["web"],
                degrade_on_critical_exit=True,
                shutdown_requested=False,
                phase_b_status=PHASE_STATUS_HEALTHY,
                phase_b_error="phase_b task failed",
                phase_b_started_at=0.0,
                readiness_grace_seconds=0.0,
            )
        )

        self.assertEqual(result.phase_b_status, PHASE_STATUS_DEGRADED)
        self.assertEqual(result.phase_b_error, "phase_b task failed")
        self.assertEqual(result.reasons, {"phase_b": "phase_b task failed"})

    def test_reported_phase_b_degraded_derives_error_from_failed_platform(self) -> None:
        result = evaluate_phase_b_health(
            PhaseBHealthInput(
                platform_statuses={"web": PHASE_STATUS_DEGRADED},
                platform_errors={"web": "sync failed"},
                critical_platforms=["web"],
                degrade_on_critical_exit=True,
                shutdown_requested=False,
                phase_b_status=PHASE_STATUS_DEGRADED,
                phase_b_error=None,
                phase_b_started_at=0.0,
                readiness_grace_seconds=0.0,
                include_starting_failures=True,
            )
        )

        self.assertEqual(result.phase_b_status, PHASE_STATUS_DEGRADED)
        self.assertEqual(result.phase_b_error, "web: sync failed")
        self.assertEqual(result.failed_critical_platforms, ["web"])
        self.assertEqual(result.reasons, {"web": "sync failed"})

    def test_reported_phase_b_degraded_without_error_uses_default_reason(self) -> None:
        result = evaluate_phase_b_health(
            PhaseBHealthInput(
                platform_statuses={"web": PHASE_STATUS_HEALTHY},
                platform_errors={"web": None},
                critical_platforms=["web"],
                degrade_on_critical_exit=True,
                shutdown_requested=False,
                phase_b_status=PHASE_STATUS_DEGRADED,
                phase_b_error=None,
                phase_b_started_at=0.0,
                readiness_grace_seconds=0.0,
            )
        )

        self.assertEqual(result.phase_b_status, PHASE_STATUS_DEGRADED)
        self.assertEqual(result.phase_b_error, "phase_b reported degraded")
        self.assertEqual(result.failed_critical_platforms, [])
        self.assertEqual(result.reasons, {"phase_b": "phase_b reported degraded"})

    def test_normalize_platform_list_and_parse_float_helpers_cover_edge_paths(self) -> None:
        self.assertEqual(
            phase_b_health_mod._normalize_platform_list("web"),  # pylint: disable=protected-access
            [],
        )
        self.assertEqual(
            phase_b_health_mod._normalize_platform_list(  # pylint: disable=protected-access
                ["web", " WEB ", "", "matrix"]
            ),
            ["web", "matrix"],
        )
        self.assertEqual(
            phase_b_health_mod._parse_nonnegative_float(  # pylint: disable=protected-access
                "bad",
                default=7.0,
            ),
            7.0,
        )
        self.assertEqual(
            phase_b_health_mod._parse_nonnegative_float(  # pylint: disable=protected-access
                -5,
                default=3.0,
            ),
            3.0,
        )

    def test_default_platform_reason_handles_starting_and_unknown(self) -> None:
        self.assertEqual(
            phase_b_health_mod._default_platform_reason(  # pylint: disable=protected-access
                platform="web",
                status=PHASE_STATUS_STARTING,
                platform_errors={},
            ),
            "web: platform still starting",
        )
        self.assertEqual(
            phase_b_health_mod._default_platform_reason(  # pylint: disable=protected-access
                platform="web",
                status="weird",
                platform_errors={},
            ),
            "web: platform status=weird",
        )

    def test_evaluate_flags_unknown_status_with_reason(self) -> None:
        result = evaluate_phase_b_health(
            PhaseBHealthInput(
                platform_statuses={"web": "weird"},
                platform_errors={"web": None},
                critical_platforms=["web"],
                degrade_on_critical_exit=True,
                shutdown_requested=False,
                phase_b_status=PHASE_STATUS_STARTING,
                phase_b_error=None,
                phase_b_started_at=0.0,
                readiness_grace_seconds=0.0,
                include_starting_failures=True,
            )
        )

        self.assertEqual(result.phase_b_status, PHASE_STATUS_DEGRADED)
        self.assertEqual(result.phase_b_error, "web: platform status=weird")
        self.assertEqual(result.failed_critical_platforms, ["web"])
        self.assertEqual(result.reasons, {"web": "platform status=weird"})

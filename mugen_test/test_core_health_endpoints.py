"""Tests for core health probe endpoints."""

import unittest
from time import perf_counter

from quart import Quart

from mugen import (
    PHASE_A_STATUS_KEY,
    PHASE_B_ERROR_KEY,
    PHASE_B_PLATFORM_ERRORS_KEY,
    PHASE_B_PLATFORM_STATUSES_KEY,
    PHASE_B_STARTED_AT_KEY,
    PHASE_B_STATUS_KEY,
    PHASE_STATUS_DEGRADED,
    PHASE_STATUS_HEALTHY,
    PHASE_STATUS_STARTING,
    PHASE_STATUS_STOPPED,
)
from mugen.core.api import api
from mugen.core.api.endpoint import (  # pylint: disable=protected-access
    _parse_bool,
    _resolve_failed_platforms,
)


class TestCoreHealthEndpoints(unittest.IsolatedAsyncioTestCase):
    """Validate liveness and readiness endpoint behavior."""

    async def asyncSetUp(self) -> None:
        self.app = Quart("core_health_test")
        self.app.register_blueprint(api, url_prefix="/api")

    def _bootstrap_state(self) -> dict:
        mugen_state = self.app.extensions.setdefault("mugen", {})
        return mugen_state.setdefault("bootstrap", {})

    async def test_live_endpoint_returns_200(self) -> None:
        state = self._bootstrap_state()
        state[PHASE_A_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_HEALTHY

        async with self.app.test_app() as test_app:
            client = test_app.test_client()
            response = await client.get("/api/core/health/live")
            payload = await response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "live")

    async def test_ready_endpoint_returns_200_when_healthy(self) -> None:
        state = self._bootstrap_state()
        state[PHASE_A_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state[PHASE_B_ERROR_KEY] = None
        state["phase_b_critical_platforms"] = ["web"]
        state[PHASE_B_PLATFORM_STATUSES_KEY] = {"web": PHASE_STATUS_HEALTHY}
        state[PHASE_B_PLATFORM_ERRORS_KEY] = {"web": None}

        async with self.app.test_app() as test_app:
            client = test_app.test_client()
            response = await client.get("/api/core/health/ready")
            payload = await response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["critical_platforms"], ["web"])
        self.assertEqual(payload["failed_platforms"], [])
        self.assertEqual(payload["reasons"], {})

    async def test_ready_endpoint_returns_503_when_phase_b_degraded(self) -> None:
        state = self._bootstrap_state()
        state[PHASE_A_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_DEGRADED
        state[PHASE_B_ERROR_KEY] = "RuntimeError: boom"
        state["phase_b_critical_platforms"] = ["web"]
        state[PHASE_B_PLATFORM_STATUSES_KEY] = {"web": PHASE_STATUS_DEGRADED}
        state[PHASE_B_PLATFORM_ERRORS_KEY] = {"web": "RuntimeError: boom"}

        async with self.app.test_app() as test_app:
            client = test_app.test_client()
            response = await client.get("/api/core/health/ready")
            payload = await response.get_json()

        self.assertEqual(response.status_code, 503)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["failed_platforms"], ["web"])
        self.assertIn("web", payload["reasons"])

    async def test_ready_endpoint_returns_503_when_starting_past_grace(self) -> None:
        state = self._bootstrap_state()
        state[PHASE_A_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STARTING
        state[PHASE_B_STARTED_AT_KEY] = perf_counter() - 10.0
        state["phase_b_readiness_grace_seconds"] = 1.0
        state["phase_b_critical_platforms"] = ["web"]
        state[PHASE_B_PLATFORM_STATUSES_KEY] = {"web": PHASE_STATUS_STARTING}
        state[PHASE_B_PLATFORM_ERRORS_KEY] = {"web": None}

        async with self.app.test_app() as test_app:
            client = test_app.test_client()
            response = await client.get("/api/core/health/ready")
            payload = await response.get_json()

        self.assertEqual(response.status_code, 503)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["failed_platforms"], ["web"])

    async def test_ready_endpoint_returns_200_when_starting_within_grace(self) -> None:
        state = self._bootstrap_state()
        state[PHASE_A_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STARTING
        state[PHASE_B_STARTED_AT_KEY] = perf_counter()
        state["phase_b_readiness_grace_seconds"] = 30.0
        state["phase_b_critical_platforms"] = ["web"]
        state[PHASE_B_PLATFORM_STATUSES_KEY] = {"web": PHASE_STATUS_STARTING}
        state[PHASE_B_PLATFORM_ERRORS_KEY] = {"web": None}

        async with self.app.test_app() as test_app:
            client = test_app.test_client()
            response = await client.get("/api/core/health/ready")
            payload = await response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["failed_platforms"], [])
        self.assertEqual(payload["reasons"], {})

    async def test_ready_endpoint_uses_strict_starting_when_grace_is_invalid(self) -> None:
        state = self._bootstrap_state()
        state[PHASE_A_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STARTING
        state[PHASE_B_STARTED_AT_KEY] = perf_counter()
        state["phase_b_readiness_grace_seconds"] = "invalid"
        state["phase_b_critical_platforms"] = ["web"]
        state[PHASE_B_PLATFORM_STATUSES_KEY] = {"web": PHASE_STATUS_STARTING}
        state[PHASE_B_PLATFORM_ERRORS_KEY] = {"web": None}

        async with self.app.test_app() as test_app:
            client = test_app.test_client()
            response = await client.get("/api/core/health/ready")
            payload = await response.get_json()

        self.assertEqual(response.status_code, 503)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["failed_platforms"], ["web"])

    async def test_ready_endpoint_uses_strict_starting_when_grace_is_negative(self) -> None:
        state = self._bootstrap_state()
        state[PHASE_A_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STARTING
        state[PHASE_B_STARTED_AT_KEY] = perf_counter()
        state["phase_b_readiness_grace_seconds"] = -1
        state["phase_b_critical_platforms"] = ["web"]
        state[PHASE_B_PLATFORM_STATUSES_KEY] = {"web": PHASE_STATUS_STARTING}
        state[PHASE_B_PLATFORM_ERRORS_KEY] = {"web": None}

        async with self.app.test_app() as test_app:
            client = test_app.test_client()
            response = await client.get("/api/core/health/ready")
            payload = await response.get_json()

        self.assertEqual(response.status_code, 503)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["failed_platforms"], ["web"])

    async def test_ready_endpoint_handles_invalid_started_at_value(self) -> None:
        state = self._bootstrap_state()
        state[PHASE_A_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STARTING
        state[PHASE_B_STARTED_AT_KEY] = "not-a-float"
        state["phase_b_readiness_grace_seconds"] = 0.0
        state["phase_b_critical_platforms"] = []
        state[PHASE_B_PLATFORM_STATUSES_KEY] = {}
        state[PHASE_B_PLATFORM_ERRORS_KEY] = {}

        async with self.app.test_app() as test_app:
            client = test_app.test_client()
            response = await client.get("/api/core/health/ready")
            payload = await response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ready"])

    async def test_ready_endpoint_starting_with_missing_started_at_uses_defaults(self) -> None:
        state = self._bootstrap_state()
        state[PHASE_A_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STARTING
        state[PHASE_B_STARTED_AT_KEY] = perf_counter() - 10.0
        state["phase_b_readiness_grace_seconds"] = 0.0
        state["phase_b_critical_platforms"] = ["web"]
        state[PHASE_B_PLATFORM_STATUSES_KEY] = {"web": PHASE_STATUS_STARTING}
        state[PHASE_B_PLATFORM_ERRORS_KEY] = {"web": None}

        async with self.app.test_app() as test_app:
            client = test_app.test_client()
            response = await client.get("/api/core/health/ready")
            payload = await response.get_json()

        self.assertEqual(response.status_code, 503)
        self.assertFalse(payload["ready"])

    async def test_ready_endpoint_with_grace_still_requires_critical_platform_health(
        self,
    ) -> None:
        state = self._bootstrap_state()
        state[PHASE_A_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STARTING
        state[PHASE_B_STARTED_AT_KEY] = None
        state["phase_b_readiness_grace_seconds"] = 30.0
        state["phase_b_critical_platforms"] = ["web"]
        state[PHASE_B_PLATFORM_STATUSES_KEY] = {"web": PHASE_STATUS_STARTING}
        state[PHASE_B_PLATFORM_ERRORS_KEY] = {"web": ""}

        async with self.app.test_app() as test_app:
            client = test_app.test_client()
            response = await client.get("/api/core/health/ready")
            payload = await response.get_json()

        self.assertEqual(response.status_code, 503)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["failed_platforms"], ["web"])
        self.assertEqual(payload["reasons"], {"web": "platform still starting"})

    async def test_ready_endpoint_ignores_invalid_platform_maps(self) -> None:
        state = self._bootstrap_state()
        state[PHASE_A_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state["phase_b_critical_platforms"] = "web"
        state[PHASE_B_PLATFORM_STATUSES_KEY] = "invalid"
        state[PHASE_B_PLATFORM_ERRORS_KEY] = "invalid"

        async with self.app.test_app() as test_app:
            client = test_app.test_client()
            response = await client.get("/api/core/health/ready")
            payload = await response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["critical_platforms"], [])

    async def test_ready_endpoint_treats_stopped_critical_as_non_failed_when_degrade_disabled(
        self,
    ) -> None:
        state = self._bootstrap_state()
        state[PHASE_A_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state["phase_b_degrade_on_critical_exit"] = False
        state["phase_b_critical_platforms"] = ["web"]
        state[PHASE_B_PLATFORM_STATUSES_KEY] = {"web": PHASE_STATUS_STOPPED}
        state[PHASE_B_PLATFORM_ERRORS_KEY] = {"web": None}

        async with self.app.test_app() as test_app:
            client = test_app.test_client()
            response = await client.get("/api/core/health/ready")
            payload = await response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["failed_platforms"], [])
        self.assertEqual(payload["reasons"], {})

    async def test_ready_endpoint_skips_blank_platform_keys_in_maps(self) -> None:
        state = self._bootstrap_state()
        state[PHASE_A_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state["phase_b_critical_platforms"] = ["web"]
        state[PHASE_B_PLATFORM_STATUSES_KEY] = {
            "": PHASE_STATUS_DEGRADED,
            "   ": PHASE_STATUS_DEGRADED,
            "web": PHASE_STATUS_HEALTHY,
        }
        state[PHASE_B_PLATFORM_ERRORS_KEY] = {
            "": "bad",
            "   ": "bad",
            "web": None,
        }

        async with self.app.test_app() as test_app:
            client = test_app.test_client()
            response = await client.get("/api/core/health/ready")
            payload = await response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ready"])

    def test_resolve_failed_platforms_reason_defaults(self) -> None:
        failed, reasons = _resolve_failed_platforms(
            critical_platforms=["starting", "stopped", "degraded", "weird"],
            platform_statuses={
                "starting": PHASE_STATUS_STARTING,
                "stopped": "stopped",
                "degraded": PHASE_STATUS_DEGRADED,
                "weird": "unknown",
            },
            platform_errors={},
            ignore_starting=False,
            degrade_on_critical_exit=True,
        )

        self.assertEqual(
            failed,
            ["starting", "stopped", "degraded", "weird"],
        )
        self.assertEqual(reasons["starting"], "platform still starting")
        self.assertEqual(reasons["stopped"], "platform stopped")
        self.assertEqual(reasons["degraded"], "platform degraded")
        self.assertEqual(reasons["weird"], "platform status=unknown")

        failed_ignore, reasons_ignore = _resolve_failed_platforms(
            critical_platforms=["starting"],
            platform_statuses={"starting": PHASE_STATUS_STARTING},
            platform_errors={"starting": ""},
            ignore_starting=True,
            degrade_on_critical_exit=True,
        )
        self.assertEqual(failed_ignore, [])
        self.assertEqual(reasons_ignore, {})

        failed_stopped_ok, reasons_stopped_ok = _resolve_failed_platforms(
            critical_platforms=["stopped"],
            platform_statuses={"stopped": PHASE_STATUS_STOPPED},
            platform_errors={},
            ignore_starting=False,
            degrade_on_critical_exit=False,
        )
        self.assertEqual(failed_stopped_ok, [])
        self.assertEqual(reasons_stopped_ok, {})

    def test_parse_bool_supports_string_values_and_default(self) -> None:
        self.assertTrue(_parse_bool("yes", default=False))
        self.assertFalse(_parse_bool("off", default=True))
        self.assertTrue(_parse_bool("invalid", default=True))
        self.assertFalse(_parse_bool(object(), default=False))

"""Tests for core health probe endpoints."""

import unittest
from time import perf_counter

from quart import Quart

from mugen import (
    PHASE_A_STATUS_KEY,
    PHASE_B_ERROR_KEY,
    PHASE_B_STARTED_AT_KEY,
    PHASE_B_STATUS_KEY,
    PHASE_STATUS_DEGRADED,
    PHASE_STATUS_HEALTHY,
    PHASE_STATUS_STARTING,
)
from mugen.core.api import api


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

        async with self.app.test_app() as test_app:
            client = test_app.test_client()
            response = await client.get("/api/core/health/ready")
            payload = await response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ready"])

    async def test_ready_endpoint_returns_503_when_phase_b_degraded(self) -> None:
        state = self._bootstrap_state()
        state[PHASE_A_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_DEGRADED
        state[PHASE_B_ERROR_KEY] = "RuntimeError: boom"

        async with self.app.test_app() as test_app:
            client = test_app.test_client()
            response = await client.get("/api/core/health/ready")
            payload = await response.get_json()

        self.assertEqual(response.status_code, 503)
        self.assertFalse(payload["ready"])

    async def test_ready_endpoint_returns_503_when_starting_past_grace(self) -> None:
        state = self._bootstrap_state()
        state[PHASE_A_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STARTING
        state[PHASE_B_STARTED_AT_KEY] = perf_counter() - 10.0
        state["phase_b_readiness_grace_seconds"] = 1.0
        state["phase_b_critical_platforms"] = ["web"]

        async with self.app.test_app() as test_app:
            client = test_app.test_client()
            response = await client.get("/api/core/health/ready")
            payload = await response.get_json()

        self.assertEqual(response.status_code, 503)
        self.assertFalse(payload["ready"])

    async def test_ready_endpoint_handles_invalid_started_at_value(self) -> None:
        state = self._bootstrap_state()
        state[PHASE_A_STATUS_KEY] = PHASE_STATUS_HEALTHY
        state[PHASE_B_STATUS_KEY] = PHASE_STATUS_STARTING
        state[PHASE_B_STARTED_AT_KEY] = "not-a-float"
        state["phase_b_readiness_grace_seconds"] = 0.0
        state["phase_b_critical_platforms"] = []

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
        state[PHASE_B_STARTED_AT_KEY] = None
        state["phase_b_readiness_grace_seconds"] = -1.0
        state["phase_b_critical_platforms"] = ["web"]

        async with self.app.test_app() as test_app:
            client = test_app.test_client()
            response = await client.get("/api/core/health/ready")
            payload = await response.get_json()

        self.assertEqual(response.status_code, 503)
        self.assertFalse(payload["ready"])

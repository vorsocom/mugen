"""Unit tests for queue job lifecycle use-case transitions."""

import unittest

from mugen.core.domain.use_case.queue_job_lifecycle import QueueJobLifecycleUseCase


class TestQueueJobLifecycleUseCase(unittest.TestCase):
    """Covers queue lifecycle invariant enforcement."""

    def setUp(self) -> None:
        self.use_case = QueueJobLifecycleUseCase()

    @staticmethod
    def _build_job(status: str) -> dict:
        return {
            "id": "job-1",
            "status": status,
            "attempts": 0,
        }

    def test_claim_accepts_pending_job(self) -> None:
        claimed = self.use_case.claim(
            job=self._build_job("pending"),
            now_iso="2026-02-27T00:00:00+00:00",
            lease_expires_at=123.0,
        )

        self.assertEqual(claimed["status"], "processing")
        self.assertEqual(claimed["attempts"], 1)
        self.assertEqual(claimed["lease_expires_at"], 123.0)

    def test_claim_rejects_non_pending_job(self) -> None:
        with self.assertRaises(ValueError):
            self.use_case.claim(
                job=self._build_job("processing"),
                now_iso="2026-02-27T00:00:00+00:00",
                lease_expires_at=123.0,
            )

    def test_complete_requires_processing_status(self) -> None:
        with self.assertRaises(ValueError):
            self.use_case.complete(
                job=self._build_job("pending"),
                now_iso="2026-02-27T00:00:00+00:00",
            )

    def test_fail_requires_processing_status(self) -> None:
        with self.assertRaises(ValueError):
            self.use_case.fail(
                job=self._build_job("done"),
                now_iso="2026-02-27T00:00:00+00:00",
                error="boom",
            )

    def test_complete_succeeds_from_processing(self) -> None:
        completed = self.use_case.complete(
            job=self._build_job("processing"),
            now_iso="2026-02-27T00:00:00+00:00",
        )

        self.assertEqual(completed["status"], "done")
        self.assertIsNone(completed["error"])
        self.assertEqual(completed["completed_at"], "2026-02-27T00:00:00+00:00")

    def test_fail_succeeds_from_processing(self) -> None:
        failed = self.use_case.fail(
            job=self._build_job("processing"),
            now_iso="2026-02-27T00:00:00+00:00",
            error="boom",
        )

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"], "boom")
        self.assertEqual(failed["completed_at"], "2026-02-27T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()

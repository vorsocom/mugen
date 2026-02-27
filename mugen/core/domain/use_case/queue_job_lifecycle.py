"""Use-case helpers for queue-job lifecycle transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class QueueJobLifecycleUseCase:
    """Apply queue lifecycle transitions with invariant checks."""

    def claim(
        self,
        *,
        job: dict[str, Any],
        now_iso: str,
        lease_expires_at: float,
    ) -> dict[str, Any]:
        self._require_dict(job)
        if job.get("status") != "pending":
            raise ValueError("Only pending jobs can be claimed")

        next_job = dict(job)
        next_job["status"] = "processing"
        next_job["attempts"] = int(next_job.get("attempts") or 0) + 1
        next_job["updated_at"] = now_iso
        next_job["lease_expires_at"] = lease_expires_at
        return next_job

    def complete(
        self,
        *,
        job: dict[str, Any],
        now_iso: str,
    ) -> dict[str, Any]:
        self._require_dict(job)
        if job.get("status") != "processing":
            raise ValueError("Only processing jobs can be completed")
        next_job = dict(job)
        next_job["status"] = "done"
        next_job["error"] = None
        next_job["lease_expires_at"] = None
        next_job["updated_at"] = now_iso
        next_job["completed_at"] = now_iso
        return next_job

    def fail(
        self,
        *,
        job: dict[str, Any],
        now_iso: str,
        error: str,
    ) -> dict[str, Any]:
        self._require_dict(job)
        if job.get("status") != "processing":
            raise ValueError("Only processing jobs can be failed")
        next_job = dict(job)
        next_job["status"] = "failed"
        next_job["error"] = str(error)
        next_job["lease_expires_at"] = None
        next_job["updated_at"] = now_iso
        next_job["completed_at"] = now_iso
        return next_job

    @staticmethod
    def _require_dict(value: Any) -> None:
        if not isinstance(value, dict):
            raise ValueError("job must be an object")

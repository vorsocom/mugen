"""Reusable audit lifecycle runner used by actions and operational workers."""

from __future__ import annotations

__all__ = ["AuditLifecycleRunner"]

import uuid
from typing import Any, Protocol


class _AuditLifecycleOps(Protocol):
    async def _run_lifecycle_impl(  # pylint: disable=protected-access
        self,
        *,
        tenant_id: uuid.UUID | None,
        non_tenant_only: bool,
        data: Any,
    ) -> dict[str, Any]:
        ...

    async def _seal_backlog_impl(  # pylint: disable=protected-access
        self,
        *,
        tenant_id: uuid.UUID | None,
        non_tenant_only: bool,
        batch_size: int,
        max_batches: int,
        dry_run: bool,
    ) -> dict[str, Any]:
        ...


class AuditLifecycleRunner:
    """Runs phased lifecycle maintenance against an audit event service."""

    def __init__(self, ops: _AuditLifecycleOps):
        self._ops = ops

    async def run_lifecycle(
        self,
        *,
        tenant_id: uuid.UUID | None,
        non_tenant_only: bool,
        data: Any,
    ) -> dict[str, Any]:
        return await self._ops._run_lifecycle_impl(  # pylint: disable=protected-access
            tenant_id=tenant_id,
            non_tenant_only=non_tenant_only,
            data=data,
        )

    async def seal_backlog(
        self,
        *,
        tenant_id: uuid.UUID | None,
        non_tenant_only: bool,
        batch_size: int,
        max_batches: int,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return await self._ops._seal_backlog_impl(  # pylint: disable=protected-access
            tenant_id=tenant_id,
            non_tenant_only=non_tenant_only,
            batch_size=batch_size,
            max_batches=max_batches,
            dry_run=dry_run,
        )

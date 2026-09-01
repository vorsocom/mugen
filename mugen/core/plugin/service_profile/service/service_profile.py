"""Provides Service Profile CRUD and lifecycle behavior."""

from __future__ import annotations

__all__ = ["ServiceProfileService"]

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    RowVersionConflict,
)
from mugen.core.plugin.acp.api.validation.generic import RowVersionValidation
from mugen.core.plugin.service_profile.contract.service import IServiceProfileService
from mugen.core.plugin.service_profile.domain import ServiceProfileDE


class ServiceProfileService(
    IRelationalService[ServiceProfileDE],
    IServiceProfileService,
):
    """Manage stable Service Profile identity and lifecycle transitions."""

    _ASSIGNMENT_TABLE = "service_profile_ingress_binding"
    _INGRESS_TABLE = "channel_orchestration_ingress_binding"

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(de_type=ServiceProfileDE, table=table, rsg=rsg, **kwargs)

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_key(value: object) -> str:
        normalized = str(value or "").strip().casefold()
        if normalized == "":
            abort(400, "Key must be non-empty.")
        return normalized

    @staticmethod
    def _normalize_display_name(value: object) -> str:
        normalized = str(value or "").strip()
        if normalized == "":
            abort(400, "DisplayName must be non-empty.")
        return normalized

    async def create(self, values: Mapping[str, Any]) -> ServiceProfileDE:
        """Create a normalized draft Service Profile."""
        payload = dict(values)
        payload["key"] = self._normalize_key(payload.get("key"))
        payload["display_name"] = self._normalize_display_name(
            payload.get("display_name")
        )
        payload["status"] = "draft"
        payload["activated_at"] = None
        payload["disabled_at"] = None
        return await super().create(payload)

    async def update_with_row_version(
        self,
        where: Mapping[str, Any],
        *,
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> ServiceProfileDE | None:
        """Normalize mutable presentation fields before an optimistic update."""
        payload = dict(changes)
        if "display_name" in payload:
            payload["display_name"] = self._normalize_display_name(
                payload["display_name"]
            )
        return await super().update_with_row_version(
            where,
            expected_row_version=expected_row_version,
            changes=payload,
        )

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> ServiceProfileDE:
        try:
            current = await self.get(
                {**dict(where), "row_version": expected_row_version}
            )
            if current is not None and current.deleted_at is None:
                return current
            base = await self.get(where)
        except SQLAlchemyError:
            abort(500)
        if base is None or base.deleted_at is not None:
            abort(404, "Service Profile not found.")
        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _has_valid_ingress_assignment(
        self,
        *,
        tenant_id: uuid.UUID,
        service_profile_id: uuid.UUID,
    ) -> bool:
        assignments = await self._rsg.find_many(
            self._ASSIGNMENT_TABLE,
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "service_profile_id": service_profile_id,
                        "is_active": True,
                    }
                )
            ],
            limit=1_000,
        )
        for assignment in assignments:
            binding = await self._rsg.get_one(
                self._INGRESS_TABLE,
                {
                    "tenant_id": tenant_id,
                    "id": assignment.get("ingress_binding_id"),
                    "is_active": True,
                },
            )
            if binding is not None:
                return True
        return False

    async def _transition(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        from_status: str,
        changes: Mapping[str, Any],
    ) -> tuple[dict[str, Any], int]:
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if current.status != from_status:
            abort(409, f"Service Profile must be {from_status} for this action.")
        service: ICrudServiceWithRowVersion[ServiceProfileDE] = self
        try:
            updated = await service.update_with_row_version(
                where,
                expected_row_version=expected_row_version,
                changes=changes,
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)
        if updated is None:
            abort(404, "Service Profile not found.")
        return "", 204

    async def action_activate(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Activate a draft profile with at least one live ingress assignment."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if current.status != "draft":
            abort(409, "Only draft Service Profiles can be activated.")
        try:
            eligible = await self._has_valid_ingress_assignment(
                tenant_id=tenant_id,
                service_profile_id=entity_id,
            )
        except SQLAlchemyError:
            abort(500)
        if not eligible:
            abort(409, "An active, valid Ingress Binding assignment is required.")
        return await self._transition(
            where=where,
            expected_row_version=expected_row_version,
            from_status="draft",
            changes={
                "status": "active",
                "activated_at": self._now_utc(),
                "disabled_at": None,
            },
        )

    async def action_disable(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Disable an active Service Profile without changing assignments."""
        return await self._transition(
            where=where,
            expected_row_version=int(data.row_version),
            from_status="active",
            changes={"status": "disabled", "disabled_at": self._now_utc()},
        )

"""Provides a CRUD service for legal hold orchestration."""

__all__ = ["LegalHoldService"]

from datetime import datetime, timezone
import uuid
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core import di
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.ops_governance.contract.service.legal_hold import (
    ILegalHoldService,
)
from mugen.core.plugin.ops_governance.domain import LegalHoldDE
from mugen.core.plugin.ops_governance.service.lifecycle_action_log import (
    LifecycleActionLogService,
)


def _registry_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_REGISTRY)


class LegalHoldService(
    IRelationalService[LegalHoldDE],
    ILegalHoldService,
):
    """CRUD + action workflow for synchronized legal hold lifecycle."""

    _LIFECYCLE_LOG_TABLE = "ops_governance_lifecycle_action_log"

    def __init__(
        self,
        table: str,
        rsg: IRelationalStorageGateway,
        registry_provider=_registry_provider,
        **kwargs,
    ):
        super().__init__(
            de_type=LegalHoldDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._registry_provider = registry_provider
        self._lifecycle_log_service = LifecycleActionLogService(
            table=self._LIFECYCLE_LOG_TABLE,
            rsg=rsg,
        )

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _normalize_required_text(value: str | None, *, field_name: str) -> str:
        text = str(value or "").strip()
        if text == "":
            abort(400, f"{field_name} must be non-empty.")
        return text

    @staticmethod
    def _normalize_resource_type(value: str | None) -> str:
        text = str(value or "").strip().lower().replace("-", "_")
        if text in {"audit_event", "auditevent", "audit"}:
            return "audit_event"
        if text in {"evidence_blob", "evidenceblob", "evidence"}:
            return "evidence_blob"
        abort(400, "ResourceType must be audit_event or evidence_blob.")

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> LegalHoldDE:
        where_with_version = dict(where)
        where_with_version["row_version"] = expected_row_version

        try:
            current = await self.get(where_with_version)
        except SQLAlchemyError:
            abort(500)

        if current is not None:
            return current

        try:
            base = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if base is None:
            abort(404, "Legal hold not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _write_lifecycle_log(
        self,
        *,
        tenant_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
        action_type: str,
        outcome: str,
        actor_user_id: uuid.UUID,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        await self._lifecycle_log_service.create(
            {
                "tenant_id": tenant_id,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "action_type": action_type,
                "outcome": outcome,
                "dry_run": False,
                "actor_user_id": actor_user_id,
                "details": dict(details or {}),
            }
        )

    def _resource_service(self, resource_name: str) -> Any:
        registry: IAdminRegistry = self._registry_provider()
        resource = registry.get_resource(resource_name)
        return registry.get_edm_service(resource.service_key)

    async def _sync_hold_state(
        self,
        *,
        tenant_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
        active: bool,
        hold_until: datetime | None,
        user_id: uuid.UUID,
        reason: str,
    ) -> None:
        now = self._now_utc()

        if resource_type == "audit_event":
            service = self._resource_service("AuditEvents")
            current = await service.get({"tenant_id": tenant_id, "id": resource_id})
            if current is None:
                abort(404, "AuditEvent target not found.")
            if active:
                await service.update(
                    {"id": resource_id},
                    {
                        "legal_hold_at": now,
                        "legal_hold_until": hold_until,
                        "legal_hold_by_user_id": user_id,
                        "legal_hold_reason": reason,
                        "legal_hold_released_at": None,
                        "legal_hold_released_by_user_id": None,
                        "legal_hold_release_reason": None,
                    },
                )
            else:
                await service.update(
                    {"id": resource_id},
                    {
                        "legal_hold_released_at": now,
                        "legal_hold_released_by_user_id": user_id,
                        "legal_hold_release_reason": reason,
                    },
                )
            return

        if resource_type == "evidence_blob":
            service = self._resource_service("EvidenceBlobs")
            current = await service.get({"tenant_id": tenant_id, "id": resource_id})
            if current is None:
                abort(404, "EvidenceBlob target not found.")
            if active:
                await service.update(
                    {"id": resource_id},
                    {
                        "legal_hold_at": now,
                        "legal_hold_until": hold_until,
                        "legal_hold_by_user_id": user_id,
                        "legal_hold_reason": reason,
                        "legal_hold_released_at": None,
                        "legal_hold_released_by_user_id": None,
                        "legal_hold_release_reason": None,
                    },
                )
            else:
                await service.update(
                    {"id": resource_id},
                    {
                        "legal_hold_released_at": now,
                        "legal_hold_released_by_user_id": user_id,
                        "legal_hold_release_reason": reason,
                    },
                )
            return

        abort(400, "Unsupported ResourceType for hold synchronization.")

    async def action_place_hold(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[dict[str, Any], int]:
        _ = where
        resource_type = self._normalize_resource_type(
            getattr(data, "resource_type", None)
        )
        resource_id = getattr(data, "resource_id", None)
        if not isinstance(resource_id, uuid.UUID):
            abort(400, "ResourceId must be a UUID.")

        reason = self._normalize_required_text(
            getattr(data, "reason", None), field_name="Reason"
        )
        hold_until = getattr(data, "hold_until", None)
        retention_class_id = getattr(data, "retention_class_id", None)
        attributes = getattr(data, "attributes", None)

        try:
            current = await self.get(
                {
                    "tenant_id": tenant_id,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "status": "active",
                }
            )
        except SQLAlchemyError:
            abort(500)

        if current is not None:
            updated = await self.update(
                {"id": current.id},
                {
                    "reason": reason,
                    "hold_until": hold_until,
                    "retention_class_id": retention_class_id,
                    "attributes": attributes,
                },
            )
            hold = updated or current
            status_code = 200
        else:
            hold = await self.create(
                {
                    "tenant_id": tenant_id,
                    "retention_class_id": retention_class_id,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "reason": reason,
                    "hold_until": hold_until,
                    "status": "active",
                    "placed_at": self._now_utc(),
                    "placed_by_user_id": auth_user_id,
                    "attributes": attributes,
                }
            )
            status_code = 201

        await self._sync_hold_state(
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            active=True,
            hold_until=hold_until,
            user_id=auth_user_id,
            reason=reason,
        )

        await self._write_lifecycle_log(
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action_type="place_hold",
            outcome="success",
            actor_user_id=auth_user_id,
            details={
                "legal_hold_id": str(hold.id),
                "hold_until": hold_until.isoformat() if hold_until else None,
            },
        )

        return {
            "LegalHoldId": str(hold.id),
            "Status": hold.status,
            "ResourceType": hold.resource_type,
            "ResourceId": str(hold.resource_id),
        }, status_code

    async def action_release_hold(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[dict[str, Any], int]:
        _ = where
        expected_row_version = int(getattr(data, "row_version"))
        hold = await self._get_for_action(
            where={"tenant_id": tenant_id, "id": entity_id},
            expected_row_version=expected_row_version,
        )

        release_reason = self._normalize_required_text(
            getattr(data, "reason", None),
            field_name="Reason",
        )

        if hold.status == "released":
            return {
                "LegalHoldId": str(hold.id),
                "Status": hold.status,
            }, 200

        try:
            updated = await self.update_with_row_version(
                where={"id": hold.id},
                expected_row_version=expected_row_version,
                changes={
                    "status": "released",
                    "released_at": self._now_utc(),
                    "released_by_user_id": auth_user_id,
                    "release_reason": release_reason,
                },
            )
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(409, "RowVersion conflict. Refresh and retry.")

        await self._sync_hold_state(
            tenant_id=tenant_id,
            resource_type=self._normalize_resource_type(updated.resource_type),
            resource_id=updated.resource_id,
            active=False,
            hold_until=updated.hold_until,
            user_id=auth_user_id,
            reason=release_reason,
        )

        await self._write_lifecycle_log(
            tenant_id=tenant_id,
            resource_type=updated.resource_type,
            resource_id=updated.resource_id,
            action_type="release_hold",
            outcome="success",
            actor_user_id=auth_user_id,
            details={
                "legal_hold_id": str(updated.id),
                "release_reason": release_reason,
            },
        )

        return {
            "LegalHoldId": str(updated.id),
            "Status": updated.status,
            "ResourceType": updated.resource_type,
            "ResourceId": str(updated.resource_id),
        }, 200

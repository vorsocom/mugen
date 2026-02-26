"""Provides a CRUD service for retention policies and lifecycle actions."""

__all__ = ["RetentionPolicyService"]

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core import di
from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    RowVersionConflict,
)
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.ops_governance.api.validation import (
    ApplyRetentionActionValidation,
)
from mugen.core.plugin.ops_governance.contract.service.retention_policy import (
    IRetentionPolicyService,
)
from mugen.core.plugin.ops_governance.domain import RetentionClassDE, RetentionPolicyDE
from mugen.core.plugin.ops_governance.service.data_handling_record import (
    DataHandlingRecordService,
)
from mugen.core.plugin.ops_governance.service.lifecycle_action_log import (
    LifecycleActionLogService,
)
from mugen.core.plugin.ops_governance.service.retention_class import (
    RetentionClassResolutionError,
    RetentionClassService,
)


def _registry_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_REGISTRY)


class RetentionPolicyService(
    IRelationalService[RetentionPolicyDE],
    IRetentionPolicyService,
):
    """A CRUD service for retention policy metadata and orchestration actions."""

    _DATA_HANDLING_TABLE = "ops_governance_data_handling_record"
    _RETENTION_CLASS_TABLE = "ops_governance_retention_class"
    _LIFECYCLE_LOG_TABLE = "ops_governance_lifecycle_action_log"

    def __init__(
        self,
        table: str,
        rsg: IRelationalStorageGateway,
        registry_provider=_registry_provider,
        **kwargs,
    ):
        super().__init__(
            de_type=RetentionPolicyDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._registry_provider = registry_provider
        self._data_handling_service = DataHandlingRecordService(
            table=self._DATA_HANDLING_TABLE,
            rsg=rsg,
        )
        self._retention_class_service = RetentionClassService(
            table=self._RETENTION_CLASS_TABLE,
            rsg=rsg,
        )
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
        clean = str(value).strip()
        return clean or None

    @staticmethod
    def _normalize_resource_type(value: str | None) -> str:
        text = str(value or "").strip().lower().replace("-", "_")
        if text in {"audit_event", "auditevent", "audit"}:
            return "audit_event"
        if text in {"evidence_blob", "evidenceblob", "evidence"}:
            return "evidence_blob"
        abort(400, f"Unsupported resource type: {value!r}.")

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> RetentionPolicyDE:
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
            abort(404, "Retention policy not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_with_row_version(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> RetentionPolicyDE:
        svc: ICrudServiceWithRowVersion[RetentionPolicyDE] = self

        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes=changes,
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return updated

    async def _resource_service(self, entity_set: str) -> Any:
        registry: IAdminRegistry = self._registry_provider()
        resource = registry.get_resource(entity_set)
        return registry.get_edm_service(resource.service_key)

    async def _write_lifecycle_log(
        self,
        *,
        tenant_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID,
        action_type: str,
        outcome: str,
        actor_user_id: uuid.UUID,
        dry_run: bool,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        await self._lifecycle_log_service.create(
            {
                "tenant_id": tenant_id,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "action_type": action_type,
                "outcome": outcome,
                "dry_run": bool(dry_run),
                "actor_user_id": actor_user_id,
                "details": dict(details or {}),
            }
        )

    async def _active_retention_classes(
        self,
        *,
        tenant_id: uuid.UUID,
    ) -> dict[str, RetentionClassDE]:
        classes: dict[str, RetentionClassDE] = {}
        for resource_type in ("audit_event", "evidence_blob"):
            try:
                resolved = await (
                    self._retention_class_service.resolve_active_for_resource_type(
                        tenant_id=tenant_id,
                        resource_type=resource_type,
                    )
                )
            except RetentionClassResolutionError as exc:
                abort(409, str(exc))
            except SQLAlchemyError:
                abort(500)
            if resolved is not None:
                classes[resource_type] = resolved
        return classes

    async def _apply_class_defaults(
        self,
        *,
        tenant_id: uuid.UUID,
        retention_class: RetentionClassDE,
        dry_run: bool,
        batch_size: int,
        max_batches: int,
    ) -> dict[str, int]:
        resource_type = self._normalize_resource_type(retention_class.resource_type)
        service = await self._resource_service(
            "AuditEvents" if resource_type == "audit_event" else "EvidenceBlobs"
        )

        retention_days = max(0, int(retention_class.retention_days or 0))
        redaction_days_raw = retention_class.redaction_after_days
        redaction_days = (
            None if redaction_days_raw is None else max(0, int(redaction_days_raw))
        )

        marked_retention = 0
        marked_redaction = 0
        batches = 0

        while batches < max_batches:
            try:
                rows = await service.list(
                    filter_groups=[
                        FilterGroup(
                            where={
                                "tenant_id": tenant_id,
                                "retention_until": None,
                            }
                        )
                    ],
                    limit=batch_size,
                )
            except SQLAlchemyError:
                abort(500)

            if not rows:
                break

            for row in rows:
                base_time = getattr(row, "occurred_at", None) or getattr(
                    row,
                    "created_at",
                    None,
                )
                if base_time is None:
                    continue

                retention_until = base_time + timedelta(days=retention_days)
                redaction_due_at = (
                    None
                    if redaction_days is None
                    else base_time + timedelta(days=redaction_days)
                )

                if dry_run:
                    marked_retention += 1
                    if redaction_due_at is not None:
                        marked_redaction += 1
                    continue

                changes: dict[str, Any] = {"retention_until": retention_until}
                if redaction_due_at is not None:
                    changes["redaction_due_at"] = redaction_due_at

                try:
                    updated = await service.update(
                        {"id": row.id},
                        changes,
                    )
                except SQLAlchemyError:
                    abort(500)

                if updated is None:
                    continue

                marked_retention += 1
                if redaction_due_at is not None:
                    marked_redaction += 1

            batches += 1
            if len(rows) < batch_size:
                break

        return {
            "MarkedRetentionUntil": marked_retention,
            "MarkedRedactionDue": marked_redaction,
        }

    async def _run_audit_lifecycle(
        self,
        *,
        tenant_id: uuid.UUID,
        dry_run: bool,
        batch_size: int,
        max_batches: int,
        now_override: datetime | None,
        purge_grace_days_override: int | None,
        auth_user_id: uuid.UUID,
    ) -> dict[str, Any]:
        service = await self._resource_service("AuditEvents")
        summary, _ = await service.action_run_lifecycle(
            tenant_id=tenant_id,
            where={"tenant_id": tenant_id},
            auth_user_id=auth_user_id,
            data=SimpleNamespace(
                batch_size=batch_size,
                max_batches=max_batches,
                dry_run=dry_run,
                now_override=now_override,
                purge_grace_days_override=purge_grace_days_override,
                phases=["redact_due", "tombstone_expired", "purge_due"],
            ),
        )
        return dict(summary)

    async def _run_evidence_lifecycle(
        self,
        *,
        tenant_id: uuid.UUID,
        dry_run: bool,
        batch_size: int,
        max_batches: int,
        now_override: datetime | None,
        purge_grace_days_override: int | None,
    ) -> dict[str, Any]:
        service = await self._resource_service("EvidenceBlobs")
        summary = await service.run_lifecycle(
            tenant_id=tenant_id,
            dry_run=dry_run,
            batch_size=batch_size,
            max_batches=max_batches,
            now_override=now_override,
            purge_grace_days_override=purge_grace_days_override,
        )
        return dict(summary)

    async def action_apply_retention_action(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: ApplyRetentionActionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Persist metadata about a retention action request."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if not bool(current.is_active):
            abort(409, "Retention policy is inactive.")

        now = self._now_utc()

        record = await self._data_handling_service.create(
            {
                "tenant_id": tenant_id,
                "retention_policy_id": entity_id,
                "subject_namespace": data.subject_namespace,
                "subject_id": data.subject_id,
                "subject_ref": self._normalize_optional_text(data.subject_ref),
                "request_type": data.action_type.strip().lower(),
                "request_status": data.request_status.strip().lower(),
                "requested_at": now,
                "due_at": data.due_at,
                "resolution_note": self._normalize_optional_text(data.note),
                "handled_by_user_id": auth_user_id,
                "evidence_blob_id": getattr(data, "evidence_blob_id", None),
                "meta": data.meta,
            }
        )

        await self._update_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "last_action_applied_at": now,
                "last_action_type": data.action_type.strip().lower(),
                "last_action_status": data.request_status.strip().lower(),
                "last_action_note": self._normalize_optional_text(data.note),
                "last_action_by_user_id": auth_user_id,
            },
        )

        return {
            "DataHandlingRecordId": str(record.id),
            "RequestStatus": record.request_status,
        }, 200

    async def action_run_lifecycle(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[dict[str, Any], int]:
        """Run deterministic lifecycle orchestration for audit + evidence targets."""
        expected_row_version = int(getattr(data, "row_version"))
        policy = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if not bool(policy.is_active):
            abort(409, "Retention policy is inactive.")

        dry_run = bool(getattr(data, "dry_run", False))
        batch_size = int(getattr(data, "batch_size", 200) or 200)
        max_batches = int(getattr(data, "max_batches", 10) or 10)
        now_override = getattr(data, "now_override", None)

        classes = await self._active_retention_classes(tenant_id=tenant_id)
        audit_class = classes.get("audit_event")
        evidence_class = classes.get("evidence_blob")

        class_marking: dict[str, dict[str, int]] = {}
        for resource_type in ("audit_event", "evidence_blob"):
            retention_class = classes.get(resource_type)
            if retention_class is None:
                continue
            class_marking[resource_type] = await self._apply_class_defaults(
                tenant_id=tenant_id,
                retention_class=retention_class,
                dry_run=dry_run,
                batch_size=batch_size,
                max_batches=max_batches,
            )

        audit_summary = await self._run_audit_lifecycle(
            tenant_id=tenant_id,
            dry_run=dry_run,
            batch_size=batch_size,
            max_batches=max_batches,
            now_override=now_override,
            purge_grace_days_override=(
                None
                if audit_class is None or audit_class.purge_grace_days is None
                else max(0, int(audit_class.purge_grace_days))
            ),
            auth_user_id=auth_user_id,
        )
        evidence_summary = await self._run_evidence_lifecycle(
            tenant_id=tenant_id,
            dry_run=dry_run,
            batch_size=batch_size,
            max_batches=max_batches,
            now_override=now_override,
            purge_grace_days_override=(
                None
                if evidence_class is None or evidence_class.purge_grace_days is None
                else max(0, int(evidence_class.purge_grace_days))
            ),
        )

        now = self._now_utc()
        if not dry_run:
            await self._write_lifecycle_log(
                tenant_id=tenant_id,
                resource_type="retention_policy",
                resource_id=entity_id,
                action_type="run_lifecycle",
                outcome="success",
                actor_user_id=auth_user_id,
                dry_run=False,
                details={
                    "audit_summary": audit_summary,
                    "evidence_summary": evidence_summary,
                    "class_marking": class_marking,
                },
            )

            await self._update_with_row_version(
                where={"tenant_id": tenant_id, "id": entity_id},
                expected_row_version=expected_row_version,
                changes={
                    "last_action_applied_at": now,
                    "last_action_type": "run_lifecycle",
                    "last_action_status": "completed",
                    "last_action_note": "lifecycle orchestration",
                    "last_action_by_user_id": auth_user_id,
                },
            )

        summary = {
            "RetentionPolicyId": str(policy.id),
            "TenantId": str(tenant_id),
            "DryRun": dry_run,
            "ClassMarking": class_marking,
            "AuditLifecycle": audit_summary,
            "EvidenceLifecycle": evidence_summary,
        }

        return summary, 200

"""Provides a CRUD service for evidence metadata and lifecycle actions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core import di
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    OrderBy,
    RowVersionConflict,
    ScalarFilter,
    ScalarFilterOp,
)
from mugen.core.plugin.acp.constants import GLOBAL_TENANT_ID
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.audit.contract.service.evidence_blob import IEvidenceBlobService
from mugen.core.plugin.audit.domain import EvidenceBlobDE

__all__ = ["EvidenceBlobService"]


def _config_provider():
    return di.container.config  # pragma: no cover


def _registry_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_REGISTRY)


class EvidenceBlobService(
    IRelationalService[EvidenceBlobDE],
    IEvidenceBlobService,
):
    """CRUD + lifecycle operations for EvidenceBlob metadata records."""

    def __init__(
        self,
        table: str,
        rsg: IRelationalStorageGateway,
        config_provider=_config_provider,
        registry_provider=_registry_provider,
        **kwargs,
    ):
        super().__init__(
            de_type=EvidenceBlobDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._config_provider = config_provider
        self._registry_provider = registry_provider

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _to_aware_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _normalize_tenant_id(value: uuid.UUID | None) -> uuid.UUID:
        return value if value is not None else GLOBAL_TENANT_ID

    @staticmethod
    def _normalize_required_text(value: str | None, *, field: str) -> str:
        text = str(value or "").strip()
        if text == "":
            abort(400, f"{field} must be non-empty.")
        return text

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _same_datetime(left: datetime | None, right: datetime | None) -> bool:
        return EvidenceBlobService._to_aware_utc(
            left
        ) == EvidenceBlobService._to_aware_utc(right)

    def _lifecycle_cfg(self) -> SimpleNamespace:
        config = self._config_provider()
        audit_cfg = getattr(config, "audit", SimpleNamespace())
        return getattr(audit_cfg, "lifecycle", SimpleNamespace())

    def _default_purge_grace_days(self) -> int:
        cfg = self._lifecycle_cfg()
        raw = getattr(cfg, "purge_grace_days", 30)
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            return 30
        return max(0, parsed)

    async def _emit_lifecycle_event(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_id: uuid.UUID,
        entity_id: uuid.UUID,
        action_name: str,
        outcome: str,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        try:
            registry: IAdminRegistry = self._registry_provider()
            resource = registry.get_resource("AuditEvents")
            audit_svc = registry.get_edm_service(resource.service_key)
        except Exception:  # pylint: disable=broad-except
            return

        try:
            await audit_svc.create(
                {
                    "tenant_id": tenant_id,
                    "actor_id": actor_id,
                    "entity_set": "EvidenceBlobs",
                    "entity": "EvidenceBlob",
                    "entity_id": entity_id,
                    "operation": "evidence_lifecycle",
                    "action_name": action_name,
                    "occurred_at": self._now_utc(),
                    "outcome": outcome,
                    "source_plugin": "com.vorsocomputing.mugen.audit",
                    "meta": dict(meta or {}),
                }
            )
        except Exception:  # pylint: disable=broad-except
            return

    @staticmethod
    def _legal_hold_is_active(row: EvidenceBlobDE, now: datetime) -> bool:
        if row.legal_hold_at is None:
            return False
        if row.legal_hold_released_at is not None:
            return False
        hold_until = EvidenceBlobService._to_aware_utc(row.legal_hold_until)
        if hold_until is None:
            return True
        return hold_until > now

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        not_found: str,
    ) -> EvidenceBlobDE:
        where_with_version = dict(where)
        where_with_version["row_version"] = expected_row_version

        try:
            row = await self.get(where_with_version)
        except SQLAlchemyError:
            abort(500)

        if row is not None:
            return row

        try:
            base = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if base is None:
            abort(404, not_found)

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _register(
        self,
        *,
        tenant_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: Any,
    ) -> tuple[dict[str, Any], int]:
        storage_uri = self._normalize_required_text(
            getattr(data, "storage_uri", None),
            field="StorageUri",
        )
        content_hash = self._normalize_required_text(
            getattr(data, "content_hash", None),
            field="ContentHash",
        ).lower()
        hash_alg = self._normalize_required_text(
            getattr(data, "hash_alg", "sha256"),
            field="HashAlg",
        ).lower()
        immutability = self._normalize_required_text(
            getattr(data, "immutability", "immutable"),
            field="Immutability",
        ).lower()
        if immutability not in {"immutable", "mutable"}:
            abort(400, "Immutability must be 'immutable' or 'mutable'.")

        try:
            existing = await self.get(
                {
                    "tenant_id": tenant_id,
                    "storage_uri": storage_uri,
                    "content_hash": content_hash,
                }
            )
        except SQLAlchemyError:
            abort(500)

        if existing is not None:
            return {
                "EvidenceBlobId": str(existing.id),
                "VerificationStatus": existing.verification_status,
            }, 200

        created = await self.create(
            {
                "tenant_id": tenant_id,
                "trace_id": self._normalize_optional_text(
                    getattr(data, "trace_id", None)
                ),
                "source_plugin": self._normalize_optional_text(
                    getattr(data, "source_plugin", None)
                ),
                "subject_namespace": self._normalize_optional_text(
                    getattr(data, "subject_namespace", None)
                ),
                "subject_id": getattr(data, "subject_id", None),
                "storage_uri": storage_uri,
                "content_hash": content_hash,
                "hash_alg": hash_alg,
                "content_length": getattr(data, "content_length", None),
                "immutability": immutability,
                "verification_status": "pending",
                "retention_until": self._to_aware_utc(
                    getattr(data, "retention_until", None)
                ),
                "redaction_due_at": self._to_aware_utc(
                    getattr(data, "redaction_due_at", None)
                ),
                "meta": getattr(data, "meta", None),
            }
        )

        await self._emit_lifecycle_event(
            tenant_id=tenant_id,
            actor_id=auth_user_id,
            entity_id=created.id,
            action_name="register",
            outcome="success",
            meta={
                "storage_uri": storage_uri,
                "content_hash": content_hash,
                "hash_alg": hash_alg,
            },
        )

        return {
            "EvidenceBlobId": str(created.id),
            "VerificationStatus": created.verification_status,
        }, 201

    async def entity_set_action_register(
        self,
        *,
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[dict[str, Any], int]:
        tenant_id = self._normalize_tenant_id(getattr(data, "tenant_id", None))
        return await self._register(
            tenant_id=tenant_id,
            auth_user_id=auth_user_id,
            data=data,
        )

    async def action_register(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[dict[str, Any], int]:
        _ = where
        return await self._register(
            tenant_id=self._normalize_tenant_id(tenant_id),
            auth_user_id=auth_user_id,
            data=data,
        )

    async def _verify_hash(
        self,
        *,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: Any,
    ) -> tuple[dict[str, Any], int]:
        expected_row_version = int(getattr(data, "row_version"))
        row = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
            not_found="Evidence blob not found.",
        )

        observed_hash = self._normalize_required_text(
            getattr(data, "observed_hash", None),
            field="ObservedHash",
        ).lower()
        observed_alg = self._normalize_required_text(
            getattr(data, "observed_hash_alg", "sha256"),
            field="ObservedHashAlg",
        ).lower()

        passed = (
            observed_hash == str(row.content_hash or "").lower()
            and observed_alg == str(row.hash_alg or "").lower()
        )
        status = "verified" if passed else "failed"

        if row.verification_status == status and row.verified_at is not None:
            return {
                "EvidenceBlobId": str(row.id),
                "Verified": passed,
                "VerificationStatus": row.verification_status,
            }, 200

        now = self._now_utc()

        try:
            updated = await self.update_with_row_version(
                where={"id": row.id},
                expected_row_version=expected_row_version,
                changes={
                    "verification_status": status,
                    "verified_at": now,
                    "verified_by_user_id": auth_user_id,
                },
            )
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(409, "RowVersion conflict. Refresh and retry.")

        await self._emit_lifecycle_event(
            tenant_id=updated.tenant_id,
            actor_id=auth_user_id,
            entity_id=updated.id,
            action_name="verify_hash",
            outcome="success" if passed else "error",
            meta={
                "verified": passed,
                "verification_status": status,
                "observed_hash_alg": observed_alg,
            },
        )

        return {
            "EvidenceBlobId": str(updated.id),
            "Verified": passed,
            "VerificationStatus": status,
        }, 200

    async def entity_action_verify_hash(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[dict[str, Any], int]:
        return await self._verify_hash(
            where={"id": entity_id},
            auth_user_id=auth_user_id,
            data=data,
        )

    async def action_verify_hash(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[dict[str, Any], int]:
        _ = where
        return await self._verify_hash(
            where={"tenant_id": tenant_id, "id": entity_id},
            auth_user_id=auth_user_id,
            data=data,
        )

    async def _place_legal_hold(
        self,
        *,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: Any,
    ) -> tuple[str, int]:
        expected_row_version = int(getattr(data, "row_version"))
        row = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
            not_found="Evidence blob not found.",
        )

        now = self._now_utc()
        until = self._to_aware_utc(getattr(data, "legal_hold_until", None))
        reason = self._normalize_required_text(
            getattr(data, "reason", None),
            field="Reason",
        )

        if self._legal_hold_is_active(row, now):
            if self._same_datetime(row.legal_hold_until, until) and (
                self._normalize_optional_text(row.legal_hold_reason) == reason
            ):
                return "", 204
            abort(409, "Evidence blob is already under legal hold.")

        try:
            updated = await self.update_with_row_version(
                where={"id": row.id},
                expected_row_version=expected_row_version,
                changes={
                    "legal_hold_at": now,
                    "legal_hold_until": until,
                    "legal_hold_by_user_id": auth_user_id,
                    "legal_hold_reason": reason,
                    "legal_hold_released_at": None,
                    "legal_hold_released_by_user_id": None,
                    "legal_hold_release_reason": None,
                },
            )
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(409, "RowVersion conflict. Refresh and retry.")

        await self._emit_lifecycle_event(
            tenant_id=updated.tenant_id,
            actor_id=auth_user_id,
            entity_id=updated.id,
            action_name="place_legal_hold",
            outcome="success",
            meta={
                "legal_hold_until": until.isoformat() if until else None,
                "reason": reason,
            },
        )
        return "", 204

    async def entity_action_place_legal_hold(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[str, int]:
        return await self._place_legal_hold(
            where={"id": entity_id},
            auth_user_id=auth_user_id,
            data=data,
        )

    async def action_place_legal_hold(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[str, int]:
        _ = where
        return await self._place_legal_hold(
            where={"tenant_id": tenant_id, "id": entity_id},
            auth_user_id=auth_user_id,
            data=data,
        )

    async def _release_legal_hold(
        self,
        *,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: Any,
    ) -> tuple[str, int]:
        expected_row_version = int(getattr(data, "row_version"))
        row = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
            not_found="Evidence blob not found.",
        )

        now = self._now_utc()
        reason = self._normalize_required_text(
            getattr(data, "reason", None),
            field="Reason",
        )

        if not self._legal_hold_is_active(row, now):
            return "", 204

        try:
            updated = await self.update_with_row_version(
                where={"id": row.id},
                expected_row_version=expected_row_version,
                changes={
                    "legal_hold_released_at": now,
                    "legal_hold_released_by_user_id": auth_user_id,
                    "legal_hold_release_reason": reason,
                },
            )
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(409, "RowVersion conflict. Refresh and retry.")

        await self._emit_lifecycle_event(
            tenant_id=updated.tenant_id,
            actor_id=auth_user_id,
            entity_id=updated.id,
            action_name="release_legal_hold",
            outcome="success",
            meta={"reason": reason},
        )
        return "", 204

    async def entity_action_release_legal_hold(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[str, int]:
        return await self._release_legal_hold(
            where={"id": entity_id},
            auth_user_id=auth_user_id,
            data=data,
        )

    async def action_release_legal_hold(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[str, int]:
        _ = where
        return await self._release_legal_hold(
            where={"tenant_id": tenant_id, "id": entity_id},
            auth_user_id=auth_user_id,
            data=data,
        )

    async def _redact(
        self,
        *,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: Any,
    ) -> tuple[str, int]:
        expected_row_version = int(getattr(data, "row_version"))
        row = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
            not_found="Evidence blob not found.",
        )

        now = self._now_utc()
        if self._legal_hold_is_active(row, now):
            abort(409, "Evidence blob is under legal hold.")

        if row.redacted_at is not None:
            return "", 204

        reason = self._normalize_required_text(
            getattr(data, "reason", None),
            field="Reason",
        )

        try:
            updated = await self.update_with_row_version(
                where={"id": row.id},
                expected_row_version=expected_row_version,
                changes={
                    "redacted_at": now,
                    "redaction_reason": reason,
                },
            )
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(409, "RowVersion conflict. Refresh and retry.")

        await self._emit_lifecycle_event(
            tenant_id=updated.tenant_id,
            actor_id=auth_user_id,
            entity_id=updated.id,
            action_name="redact",
            outcome="success",
            meta={"reason": reason},
        )
        return "", 204

    async def entity_action_redact(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[str, int]:
        return await self._redact(
            where={"id": entity_id},
            auth_user_id=auth_user_id,
            data=data,
        )

    async def action_redact(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[str, int]:
        _ = where
        return await self._redact(
            where={"tenant_id": tenant_id, "id": entity_id},
            auth_user_id=auth_user_id,
            data=data,
        )

    async def _tombstone(
        self,
        *,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: Any,
    ) -> tuple[str, int]:
        expected_row_version = int(getattr(data, "row_version"))
        row = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
            not_found="Evidence blob not found.",
        )

        now = self._now_utc()
        if self._legal_hold_is_active(row, now):
            abort(409, "Evidence blob is under legal hold.")

        if row.tombstoned_at is not None:
            return "", 204

        purge_after_days = getattr(data, "purge_after_days", None)
        if purge_after_days is None:
            purge_days = self._default_purge_grace_days()
        else:
            purge_days = max(0, int(purge_after_days))

        reason = self._normalize_required_text(
            getattr(data, "reason", None),
            field="Reason",
        )

        try:
            updated = await self.update_with_row_version(
                where={"id": row.id},
                expected_row_version=expected_row_version,
                changes={
                    "tombstoned_at": now,
                    "tombstoned_by_user_id": auth_user_id,
                    "tombstone_reason": reason,
                    "purge_due_at": now + timedelta(days=purge_days),
                },
            )
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(409, "RowVersion conflict. Refresh and retry.")

        await self._emit_lifecycle_event(
            tenant_id=updated.tenant_id,
            actor_id=auth_user_id,
            entity_id=updated.id,
            action_name="tombstone",
            outcome="success",
            meta={
                "reason": reason,
                "purge_after_days": purge_days,
            },
        )

        return "", 204

    async def entity_action_tombstone(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[str, int]:
        return await self._tombstone(
            where={"id": entity_id},
            auth_user_id=auth_user_id,
            data=data,
        )

    async def action_tombstone(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[str, int]:
        _ = where
        return await self._tombstone(
            where={"tenant_id": tenant_id, "id": entity_id},
            auth_user_id=auth_user_id,
            data=data,
        )

    async def _purge(
        self,
        *,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: Any,
    ) -> tuple[str, int]:
        expected_row_version = int(getattr(data, "row_version"))
        row = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
            not_found="Evidence blob not found.",
        )

        now = self._now_utc()
        if self._legal_hold_is_active(row, now):
            abort(409, "Evidence blob is under legal hold.")

        if row.purged_at is not None:
            return "", 204

        reason = self._normalize_required_text(
            getattr(data, "reason", None),
            field="Reason",
        )

        try:
            updated = await self.update_with_row_version(
                where={"id": row.id},
                expected_row_version=expected_row_version,
                changes={
                    "purged_at": now,
                    "purged_by_user_id": auth_user_id,
                    "purge_reason": reason,
                },
            )
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(409, "RowVersion conflict. Refresh and retry.")

        await self._emit_lifecycle_event(
            tenant_id=updated.tenant_id,
            actor_id=auth_user_id,
            entity_id=updated.id,
            action_name="purge",
            outcome="success",
            meta={"reason": reason},
        )

        return "", 204

    async def entity_action_purge(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[str, int]:
        return await self._purge(
            where={"id": entity_id},
            auth_user_id=auth_user_id,
            data=data,
        )

    async def action_purge(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[str, int]:
        _ = where
        return await self._purge(
            where={"tenant_id": tenant_id, "id": entity_id},
            auth_user_id=auth_user_id,
            data=data,
        )

    async def _phase_redact_due(
        self,
        *,
        tenant_id: uuid.UUID | None,
        dry_run: bool,
        batch_size: int,
        max_batches: int,
        now: datetime,
    ) -> dict[str, Any]:
        base: dict[str, Any] = {}
        if tenant_id is not None:
            base["tenant_id"] = tenant_id

        filters = [
            FilterGroup(
                where={**base, "redacted_at": None},
                scalar_filters=[
                    ScalarFilter(
                        field="redaction_due_at",
                        op=ScalarFilterOp.LTE,
                        value=now,
                    )
                ],
            )
        ]

        if dry_run:
            try:
                planned = await self.count(filter_groups=filters)
            except SQLAlchemyError:
                abort(500)
            return {
                "RowsPlanned": planned,
                "RowsProcessed": 0,
                "DryRun": True,
            }

        processed = 0
        batches = 0
        while batches < max_batches:
            try:
                rows = await self.list(
                    filter_groups=filters,
                    order_by=[OrderBy(field="redaction_due_at"), OrderBy(field="id")],
                    limit=batch_size,
                )
            except SQLAlchemyError:
                abort(500)

            if not rows:
                break

            batch_count = 0
            for row in rows:
                if self._legal_hold_is_active(row, now):
                    continue

                try:
                    updated = await self.update_with_row_version(
                        where={"id": row.id},
                        expected_row_version=int(row.row_version or 1),
                        changes={
                            "redacted_at": now,
                            "redaction_reason": "lifecycle:redact_due",
                        },
                    )
                except RowVersionConflict:
                    continue
                except SQLAlchemyError:
                    abort(500)

                if updated is None:
                    continue

                batch_count += 1

            processed += batch_count
            batches += 1

            if batch_count == 0:
                break

        return {
            "RowsProcessed": processed,
            "Batches": batches,
            "DryRun": False,
        }

    async def _phase_tombstone_expired(
        self,
        *,
        tenant_id: uuid.UUID | None,
        dry_run: bool,
        batch_size: int,
        max_batches: int,
        now: datetime,
    ) -> dict[str, Any]:
        base: dict[str, Any] = {}
        if tenant_id is not None:
            base["tenant_id"] = tenant_id

        filters = [
            FilterGroup(
                where={**base, "tombstoned_at": None},
                scalar_filters=[
                    ScalarFilter(
                        field="retention_until",
                        op=ScalarFilterOp.LTE,
                        value=now,
                    )
                ],
            )
        ]

        if dry_run:
            try:
                planned = await self.count(filter_groups=filters)
            except SQLAlchemyError:
                abort(500)
            return {
                "RowsPlanned": planned,
                "RowsProcessed": 0,
                "DryRun": True,
            }

        processed = 0
        batches = 0
        grace_days = self._default_purge_grace_days()
        while batches < max_batches:
            try:
                rows = await self.list(
                    filter_groups=filters,
                    order_by=[OrderBy(field="retention_until"), OrderBy(field="id")],
                    limit=batch_size,
                )
            except SQLAlchemyError:
                abort(500)

            if not rows:
                break

            batch_count = 0
            for row in rows:
                if self._legal_hold_is_active(row, now):
                    continue

                try:
                    updated = await self.update_with_row_version(
                        where={"id": row.id},
                        expected_row_version=int(row.row_version or 1),
                        changes={
                            "tombstoned_at": now,
                            "tombstone_reason": "lifecycle:retention_expired",
                            "purge_due_at": now + timedelta(days=grace_days),
                        },
                    )
                except RowVersionConflict:
                    continue
                except SQLAlchemyError:
                    abort(500)

                if updated is None:
                    continue

                batch_count += 1

            processed += batch_count
            batches += 1

            if batch_count == 0:
                break

        return {
            "RowsProcessed": processed,
            "Batches": batches,
            "DryRun": False,
        }

    async def _phase_purge_due(
        self,
        *,
        tenant_id: uuid.UUID | None,
        dry_run: bool,
        batch_size: int,
        max_batches: int,
        now: datetime,
    ) -> dict[str, Any]:
        base: dict[str, Any] = {"purged_at": None}
        if tenant_id is not None:
            base["tenant_id"] = tenant_id

        filters = [
            FilterGroup(
                where=base,
                scalar_filters=[
                    ScalarFilter(
                        field="tombstoned_at",
                        op=ScalarFilterOp.LTE,
                        value=now,
                    ),
                    ScalarFilter(
                        field="purge_due_at",
                        op=ScalarFilterOp.LTE,
                        value=now,
                    ),
                ],
            )
        ]

        if dry_run:
            try:
                planned = await self.count(filter_groups=filters)
            except SQLAlchemyError:
                abort(500)
            return {
                "RowsPlanned": planned,
                "RowsProcessed": 0,
                "DryRun": True,
            }

        processed = 0
        batches = 0
        while batches < max_batches:
            try:
                rows = await self.list(
                    filter_groups=filters,
                    order_by=[OrderBy(field="purge_due_at"), OrderBy(field="id")],
                    limit=batch_size,
                )
            except SQLAlchemyError:
                abort(500)

            if not rows:
                break

            batch_count = 0
            for row in rows:
                if self._legal_hold_is_active(row, now):
                    continue

                try:
                    updated = await self.update_with_row_version(
                        where={"id": row.id},
                        expected_row_version=int(row.row_version or 1),
                        changes={
                            "purged_at": now,
                            "purge_reason": "lifecycle:purge_due",
                        },
                    )
                except RowVersionConflict:
                    continue
                except SQLAlchemyError:
                    abort(500)

                if updated is None:
                    continue

                batch_count += 1

            processed += batch_count
            batches += 1

            if batch_count == 0:
                break

        return {
            "RowsProcessed": processed,
            "Batches": batches,
            "DryRun": False,
        }

    async def run_lifecycle(
        self,
        *,
        tenant_id: uuid.UUID | None,
        dry_run: bool,
        batch_size: int,
        max_batches: int,
        now_override: datetime | None = None,
    ) -> dict[str, Any]:
        now = self._to_aware_utc(now_override) or self._now_utc()

        phase_results = {
            "redact_due": await self._phase_redact_due(
                tenant_id=tenant_id,
                dry_run=dry_run,
                batch_size=batch_size,
                max_batches=max_batches,
                now=now,
            ),
            "tombstone_expired": await self._phase_tombstone_expired(
                tenant_id=tenant_id,
                dry_run=dry_run,
                batch_size=batch_size,
                max_batches=max_batches,
                now=now,
            ),
            "purge_due": await self._phase_purge_due(
                tenant_id=tenant_id,
                dry_run=dry_run,
                batch_size=batch_size,
                max_batches=max_batches,
                now=now,
            ),
        }

        return {
            "TenantId": str(tenant_id) if tenant_id is not None else None,
            "DryRun": bool(dry_run),
            "Now": now.isoformat(),
            "PhaseResults": phase_results,
        }

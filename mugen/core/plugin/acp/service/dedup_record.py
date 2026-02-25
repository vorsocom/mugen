"""Provides a service for the DedupRecord declarative model."""

__all__ = ["DedupRecordService"]

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

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
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.contract.service.dedup_record import IDedupRecordService
from mugen.core.plugin.acp.domain import DedupRecordDE

_DEFAULT_TTL_SECONDS = 60 * 60
_DEFAULT_LEASE_SECONDS = 30
_DEFAULT_SWEEP_BATCH_SIZE = 500


def _config_provider():
    return di.container.config


class DedupRecordService(
    IRelationalService[DedupRecordDE],
    IDedupRecordService,
):
    """A service for ACP shared idempotency ledger records."""

    def __init__(
        self,
        table: str,
        rsg: IRelationalStorageGateway,
        config_provider=_config_provider,
        **kwargs,
    ):
        super().__init__(
            de_type=DedupRecordDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._config_provider = config_provider

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_tenant_id(tenant_id: uuid.UUID | None) -> uuid.UUID:
        return tenant_id if tenant_id is not None else GLOBAL_TENANT_ID

    @staticmethod
    def _normalize_text(value: str | None, *, field: str) -> str:
        text = (value or "").strip()
        if text == "":
            abort(400, f"{field} must be non-empty.")
        return text

    @staticmethod
    def _parse_positive_int(raw: Any) -> int | None:
        if raw is None:
            return None
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            return None
        if parsed <= 0:
            return None
        return parsed

    def _idempotency_cfg(self) -> SimpleNamespace:
        config = self._config_provider()
        acp_cfg = getattr(config, "acp", SimpleNamespace())
        return getattr(acp_cfg, "idempotency", SimpleNamespace())

    def _default_ttl_seconds(self) -> int:
        cfg = self._idempotency_cfg()
        return (
            self._parse_positive_int(getattr(cfg, "default_ttl_seconds", None))
            or _DEFAULT_TTL_SECONDS
        )

    def _default_lease_seconds(self) -> int:
        cfg = self._idempotency_cfg()
        return (
            self._parse_positive_int(getattr(cfg, "default_lease_seconds", None))
            or _DEFAULT_LEASE_SECONDS
        )

    def _strict_request_hash(self) -> bool:
        cfg = self._idempotency_cfg()
        return bool(getattr(cfg, "strict_request_hash", False))

    def _resolve_ttl_seconds(self, override: int | None) -> int:
        return self._parse_positive_int(override) or self._default_ttl_seconds()

    def _resolve_lease_seconds(self, override: int | None) -> int:
        return self._parse_positive_int(override) or self._default_lease_seconds()

    @staticmethod
    def _is_expired(expires_at: datetime | None, now: datetime) -> bool:
        if expires_at is None:
            return False
        return expires_at <= now

    @staticmethod
    def _lease_active(lease_expires_at: datetime | None, now: datetime) -> bool:
        if lease_expires_at is None:
            return False
        return lease_expires_at > now

    @staticmethod
    def _serialize_datetime(value: datetime | None) -> str | None:
        if value is None:
            return None
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()

    async def acquire(
        self,
        *,
        tenant_id: uuid.UUID | None,
        scope: str,
        idempotency_key: str,
        request_hash: str | None,
        owner_instance: str | None,
        ttl_seconds: int | None = None,
        lease_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Acquire or replay a dedup record."""
        now = self._now_utc()
        normalized_tenant_id = self._normalize_tenant_id(tenant_id)
        normalized_scope = self._normalize_text(scope, field="Scope")
        normalized_key = self._normalize_text(
            idempotency_key,
            field="IdempotencyKey",
        )
        normalized_hash = (request_hash or "").strip() or None

        resolved_ttl_seconds = self._resolve_ttl_seconds(ttl_seconds)
        resolved_lease_seconds = self._resolve_lease_seconds(lease_seconds)

        where = {
            "tenant_id": normalized_tenant_id,
            "scope": normalized_scope,
            "idempotency_key": normalized_key,
        }

        record = await self.get(where)
        if record is None:
            try:
                created = await self.create(
                    {
                        "tenant_id": normalized_tenant_id,
                        "scope": normalized_scope,
                        "idempotency_key": normalized_key,
                        "request_hash": normalized_hash,
                        "status": "in_progress",
                        "owner_instance": owner_instance,
                        "lease_expires_at": (
                            now + timedelta(seconds=resolved_lease_seconds)
                        ),
                        "expires_at": now + timedelta(seconds=resolved_ttl_seconds),
                    }
                )
                return {
                    "decision": "acquired",
                    "record": created,
                }
            except IntegrityError:
                record = await self.get(where)
                if record is None:
                    abort(500, "Failed to acquire dedup record.")
            except SQLAlchemyError:
                abort(500)

        if self._is_expired(record.expires_at, now):
            try:
                updated_expired = await self.update_with_row_version(
                    {"id": record.id},
                    expected_row_version=int(record.row_version or 1),
                    changes={
                        "request_hash": normalized_hash,
                        "status": "in_progress",
                        "result_ref": None,
                        "response_code": None,
                        "response_payload": None,
                        "error_code": None,
                        "error_message": None,
                        "owner_instance": owner_instance,
                        "lease_expires_at": now
                        + timedelta(seconds=resolved_lease_seconds),
                        "expires_at": now + timedelta(seconds=resolved_ttl_seconds),
                    },
                )
            except RowVersionConflict:
                updated_expired = await self.get(where)
            except SQLAlchemyError:
                abort(500)

            if updated_expired is not None:
                return {
                    "decision": "acquired",
                    "record": updated_expired,
                }

            abort(500, "Failed to reacquire expired dedup record.")

        if self._strict_request_hash():
            existing_hash = (record.request_hash or "").strip() or None
            if (
                existing_hash is not None
                and normalized_hash is not None
                and existing_hash != normalized_hash
            ):
                return {
                    "decision": "conflict",
                    "record": record,
                    "message": "Idempotency request hash mismatch.",
                }

        if record.status in {"succeeded", "failed"}:
            return {
                "decision": "replay",
                "record": record,
                "response_code": int(record.response_code or 200),
                "response_payload": record.response_payload,
            }

        lease_active = self._lease_active(record.lease_expires_at, now)
        if (
            lease_active
            and owner_instance is not None
            and record.owner_instance is not None
            and owner_instance != record.owner_instance
        ):
            return {
                "decision": "in_progress",
                "record": record,
            }

        try:
            updated = await self.update_with_row_version(
                {"id": record.id},
                expected_row_version=int(record.row_version or 1),
                changes={
                    "request_hash": normalized_hash,
                    "owner_instance": owner_instance,
                    "lease_expires_at": now + timedelta(seconds=resolved_lease_seconds),
                    "expires_at": now + timedelta(seconds=resolved_ttl_seconds),
                },
            )
        except RowVersionConflict:
            updated = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        return {
            "decision": "acquired",
            "record": updated or record,
        }

    async def commit_success(
        self,
        *,
        entity_id: uuid.UUID,
        response_code: int,
        response_payload: Any,
        result_ref: str | None,
        ttl_seconds: int | None = None,
    ) -> None:
        """Commit success payload for a dedup record."""
        row = await self.get({"id": entity_id})
        if row is None:
            abort(404, "Dedup record not found.")

        if row.status != "in_progress":
            abort(409, "Dedup record is already finalized.")

        now = self._now_utc()
        resolved_ttl_seconds = self._resolve_ttl_seconds(ttl_seconds)

        try:
            updated = await self.update_with_row_version(
                {"id": entity_id},
                expected_row_version=int(row.row_version or 1),
                changes={
                    "status": "succeeded",
                    "result_ref": (result_ref or "").strip() or None,
                    "response_code": int(response_code),
                    "response_payload": response_payload,
                    "error_code": None,
                    "error_message": None,
                    "owner_instance": None,
                    "lease_expires_at": None,
                    "expires_at": now + timedelta(seconds=resolved_ttl_seconds),
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Commit not performed. No row matched.")

    async def commit_failure(
        self,
        *,
        entity_id: uuid.UUID,
        response_code: int,
        response_payload: Any,
        error_code: str | None,
        error_message: str | None,
        ttl_seconds: int | None = None,
    ) -> None:
        """Commit failure payload for a dedup record."""
        row = await self.get({"id": entity_id})
        if row is None:
            abort(404, "Dedup record not found.")

        if row.status != "in_progress":
            abort(409, "Dedup record is already finalized.")

        now = self._now_utc()
        resolved_ttl_seconds = self._resolve_ttl_seconds(ttl_seconds)

        try:
            updated = await self.update_with_row_version(
                {"id": entity_id},
                expected_row_version=int(row.row_version or 1),
                changes={
                    "status": "failed",
                    "result_ref": None,
                    "response_code": int(response_code),
                    "response_payload": response_payload,
                    "error_code": (error_code or "").strip() or None,
                    "error_message": (error_message or "").strip() or None,
                    "owner_instance": None,
                    "lease_expires_at": None,
                    "expires_at": now + timedelta(seconds=resolved_ttl_seconds),
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Commit not performed. No row matched.")

    async def sweep_expired(
        self,
        *,
        tenant_id: uuid.UUID | None,
        batch_size: int | None,
    ) -> int:
        """Delete expired dedup records in one bounded batch."""
        now = self._now_utc()
        resolved_batch_size = (
            self._parse_positive_int(batch_size) or _DEFAULT_SWEEP_BATCH_SIZE
        )

        where: dict[str, Any] = {}
        if tenant_id is not None:
            where["tenant_id"] = self._normalize_tenant_id(tenant_id)

        rows = await self.list(
            filter_groups=[
                FilterGroup(
                    where=where,
                    scalar_filters=[
                        ScalarFilter(
                            field="expires_at",
                            op=ScalarFilterOp.LTE,
                            value=now,
                        )
                    ],
                )
            ],
            order_by=[
                OrderBy("expires_at", descending=False),
                OrderBy("id", descending=False),
            ],
            limit=resolved_batch_size,
        )

        deleted_count = 0
        for row in rows:
            try:
                deleted = await self.delete({"id": row.id})
            except SQLAlchemyError:
                abort(500)
            if deleted is not None:
                deleted_count += 1

        return deleted_count

    def _format_action_result(self, result: dict[str, Any]) -> dict[str, Any]:
        record: DedupRecordDE | None = result.get("record")
        payload: dict[str, Any] = {
            "Decision": result.get("decision"),
            "Id": str(record.id) if record and record.id is not None else None,
            "Status": record.status if record is not None else None,
            "LeaseExpiresAt": (
                self._serialize_datetime(record.lease_expires_at)
                if record is not None
                else None
            ),
        }

        if result.get("decision") == "replay":
            payload["ResponseCode"] = int(result.get("response_code") or 200)
            payload["ResponsePayload"] = result.get("response_payload")
            payload["ResultRef"] = record.result_ref if record is not None else None
            payload["ErrorCode"] = record.error_code if record is not None else None
            payload["ErrorMessage"] = (
                record.error_message if record is not None else None
            )

        return payload

    async def entity_set_action_acquire(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Acquire (or replay) a dedup record."""
        _ = auth_user_id
        result = await self.acquire(
            tenant_id=getattr(data, "tenant_id", None),
            scope=data.scope,
            idempotency_key=data.idempotency_key,
            request_hash=getattr(data, "request_hash", None),
            owner_instance=getattr(data, "owner_instance", None),
            ttl_seconds=getattr(data, "ttl_seconds", None),
            lease_seconds=getattr(data, "lease_seconds", None),
        )

        if result["decision"] == "conflict":
            abort(409, result.get("message") or "Idempotency request hash mismatch.")

        return self._format_action_result(result), 200

    async def action_acquire(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Acquire (or replay) a tenant-scoped dedup record."""
        _ = where
        _ = auth_user_id
        result = await self.acquire(
            tenant_id=tenant_id,
            scope=data.scope,
            idempotency_key=data.idempotency_key,
            request_hash=getattr(data, "request_hash", None),
            owner_instance=getattr(data, "owner_instance", None),
            ttl_seconds=getattr(data, "ttl_seconds", None),
            lease_seconds=getattr(data, "lease_seconds", None),
        )

        if result["decision"] == "conflict":
            abort(409, result.get("message") or "Idempotency request hash mismatch.")

        return self._format_action_result(result), 200

    async def entity_action_commit_success(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Commit success payload to a dedup record."""
        _ = auth_user_id
        await self.commit_success(
            entity_id=entity_id,
            response_code=int(getattr(data, "response_code", 200)),
            response_payload=getattr(data, "response_payload", None),
            result_ref=getattr(data, "result_ref", None),
            ttl_seconds=getattr(data, "ttl_seconds", None),
        )
        return "", 204

    async def action_commit_success(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Commit tenant-scoped success payload to a dedup record."""
        _ = tenant_id
        _ = where
        _ = auth_user_id
        await self.commit_success(
            entity_id=entity_id,
            response_code=int(getattr(data, "response_code", 200)),
            response_payload=getattr(data, "response_payload", None),
            result_ref=getattr(data, "result_ref", None),
            ttl_seconds=getattr(data, "ttl_seconds", None),
        )
        return "", 204

    async def entity_action_commit_failure(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Commit failure payload to a dedup record."""
        _ = auth_user_id
        await self.commit_failure(
            entity_id=entity_id,
            response_code=int(getattr(data, "response_code", 500)),
            response_payload=getattr(data, "response_payload", None),
            error_code=getattr(data, "error_code", None),
            error_message=getattr(data, "error_message", None),
            ttl_seconds=getattr(data, "ttl_seconds", None),
        )
        return "", 204

    async def action_commit_failure(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[str, int]:
        """Commit tenant-scoped failure payload to a dedup record."""
        _ = tenant_id
        _ = where
        _ = auth_user_id
        await self.commit_failure(
            entity_id=entity_id,
            response_code=int(getattr(data, "response_code", 500)),
            response_payload=getattr(data, "response_payload", None),
            error_code=getattr(data, "error_code", None),
            error_message=getattr(data, "error_message", None),
            ttl_seconds=getattr(data, "ttl_seconds", None),
        )
        return "", 204

    async def entity_set_action_sweep_expired(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Sweep expired dedup rows for all tenants."""
        _ = auth_user_id
        deleted_count = await self.sweep_expired(
            tenant_id=getattr(data, "tenant_id", None),
            batch_size=getattr(data, "batch_size", None),
        )
        return {
            "DeletedCount": deleted_count,
        }, 200

    async def action_sweep_expired(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Sweep expired dedup rows for a tenant."""
        _ = where
        _ = auth_user_id
        deleted_count = await self.sweep_expired(
            tenant_id=tenant_id,
            batch_size=getattr(data, "batch_size", None),
        )
        return {
            "DeletedCount": deleted_count,
        }, 200

"""Provides a CRUD service for audit events."""

from __future__ import annotations

__all__ = ["AuditEventService"]

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

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
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.service import IKeyRefService
from mugen.core.plugin.audit.contract.service.audit_event import IAuditEventService
from mugen.core.plugin.audit.domain import AuditEventDE
from mugen.core.plugin.audit.service.lifecycle_runner import AuditLifecycleRunner

_GENESIS_HASH = "0" * 64
_DEFAULT_HASH_KEY_ID = "default"
_DEFAULT_HASH_SECRET = "mugen-audit-default-chain-key"
_DEFAULT_PHASES = ("seal_backlog", "redact_due", "tombstone_expired", "purge_due")
_CHAIN_HEAD_TABLE = "audit_chain_head"
_MAX_CHAIN_MISMATCH_DETAILS = 100


def _config_provider():
    return di.container.config  # pragma: no cover


def _registry_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_REGISTRY)


class AuditEventService(  # pragma: no cover
    IRelationalService[AuditEventDE],
    IAuditEventService,
):
    """A CRUD service for audit events with chain integrity and lifecycle actions."""

    _ENTRY_HASH_FIELDS = (
        "id",
        "tenant_id",
        "actor_id",
        "entity_set",
        "entity",
        "entity_id",
        "operation",
        "action_name",
        "occurred_at",
        "outcome",
        "request_id",
        "correlation_id",
        "source_plugin",
        "changed_fields",
        "meta",
        "retention_until",
        "redaction_due_at",
        "scope_key",
        "scope_seq",
        "prev_entry_hash",
        "hash_alg",
        "hash_key_id",
        "before_snapshot_hash",
        "after_snapshot_hash",
    )

    def __init__(
        self,
        table: str,
        rsg: IRelationalStorageGateway,
        config_provider=_config_provider,
        registry_provider=_registry_provider,
        max_chain_retries: int = 8,
        **kwargs,
    ):
        super().__init__(
            de_type=AuditEventDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._config_provider = config_provider
        self._registry_provider = registry_provider
        self._max_chain_retries = max(1, int(max_chain_retries))

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
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        return clean or None

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, uuid.UUID):
            return str(value)

        if isinstance(value, datetime):
            dt = value
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()

        if isinstance(value, Mapping):
            return {str(k): AuditEventService._json_safe(v) for k, v in value.items()}

        if isinstance(value, (list, tuple, set)):
            return [AuditEventService._json_safe(v) for v in value]

        if hasattr(value, "__dict__"):
            return {
                str(k): AuditEventService._json_safe(v)
                for k, v in vars(value).items()
                if not str(k).startswith("_")
            }

        return str(value)

    @staticmethod
    def _canonical_json_bytes(value: Any) -> bytes:
        return json.dumps(
            AuditEventService._json_safe(value),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    @staticmethod
    def _snapshot_hash(value: Any) -> str:
        return hashlib.sha256(  # noqa: S324
            AuditEventService._canonical_json_bytes(value)
        ).hexdigest()

    @staticmethod
    def _normalize_changed_fields(value: Any) -> list[str] | None:
        if value is None:
            return None

        if not isinstance(value, (list, tuple, set)):
            return None

        seen: set[str] = set()
        output: list[str] = []
        for item in value:
            text = str(item).strip()
            if text == "" or text in seen:
                continue
            seen.add(text)
            output.append(text)
        return output or None

    def _audit_config(self) -> SimpleNamespace:
        config = self._config_provider()
        return getattr(config, "audit", SimpleNamespace())

    @staticmethod
    def _to_mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return {str(k): v for k, v in value.items()}
        if isinstance(value, SimpleNamespace):
            return vars(value)
        return {}

    @staticmethod
    def _resolve_secret(raw: Any) -> str | None:
        if raw is None:
            return None

        if isinstance(raw, Mapping):
            env_name = str(raw.get("env", "")).strip()
            if env_name:
                env_value = os.getenv(env_name, "").strip()
                return env_value or None

            value = str(raw.get("value", "")).strip()
            return value or None

        value = str(raw).strip()
        if value == "":
            return None

        if value.lower().startswith("env:"):
            env_name = value.split(":", 1)[1].strip()
            env_value = os.getenv(env_name, "").strip()
            return env_value or None

        return value

    def _hash_chain_config(self) -> tuple[str, dict[str, Any], bool]:
        audit_cfg = self._audit_config()
        emit_cfg = getattr(audit_cfg, "emit", SimpleNamespace())
        hash_cfg = getattr(audit_cfg, "hash_chain", SimpleNamespace())

        active_kid = str(getattr(hash_cfg, "active_key_id", "")).strip()
        if active_kid == "":
            active_kid = _DEFAULT_HASH_KEY_ID

        keys = self._to_mapping(getattr(hash_cfg, "keys", {}))
        fail_closed = bool(getattr(emit_cfg, "fail_closed", False))
        return active_kid, keys, fail_closed

    def _safe_registry(self) -> IAdminRegistry | None:
        try:
            return self._registry_provider()
        except Exception:  # pylint: disable=broad-except
            return None

    async def _active_hash_material(
        self,
        *,
        tenant_id: uuid.UUID | None,
    ) -> tuple[str, bytes]:
        registry = self._safe_registry()
        if registry is not None:
            try:
                resource = registry.get_resource("KeyRefs")
                key_ref_svc: IKeyRefService = registry.get_edm_service(
                    resource.service_key
                )
                resolved = await key_ref_svc.resolve_secret_for_purpose(
                    tenant_id=tenant_id,
                    purpose="audit_hmac",
                )
                if resolved is not None:
                    return resolved.key_id, resolved.secret
            except Exception:  # pylint: disable=broad-except
                pass

        active_kid, keys, fail_closed = self._hash_chain_config()
        secret = self._resolve_secret(keys.get(active_kid))
        if secret is None:
            if fail_closed:
                raise RuntimeError(
                    f"Missing audit hash-chain secret for key id {active_kid!r}."
                )
            secret = _DEFAULT_HASH_SECRET
        return active_kid, secret.encode("utf-8")

    def _config_secret_for_kid(self, hash_key_id: str | None) -> bytes | None:
        key_id = (hash_key_id or _DEFAULT_HASH_KEY_ID).strip() or _DEFAULT_HASH_KEY_ID
        _, keys, _ = self._hash_chain_config()
        secret = self._resolve_secret(keys.get(key_id))
        if secret is not None:
            return secret.encode("utf-8")
        if key_id == _DEFAULT_HASH_KEY_ID:
            return _DEFAULT_HASH_SECRET.encode("utf-8")
        return None

    async def _secret_for_kid(
        self,
        *,
        tenant_id: uuid.UUID | None,
        hash_key_id: str | None,
        key_cache: dict[tuple[uuid.UUID | None, str], bytes | None],
    ) -> bytes | None:
        key_id = (hash_key_id or _DEFAULT_HASH_KEY_ID).strip() or _DEFAULT_HASH_KEY_ID
        cache_key = (tenant_id, key_id.casefold())
        if cache_key in key_cache:
            return key_cache[cache_key]

        secret: bytes | None = None
        registry = self._safe_registry()
        if registry is not None:
            try:
                resource = registry.get_resource("KeyRefs")
                key_ref_svc: IKeyRefService = registry.get_edm_service(
                    resource.service_key
                )
                resolved = await key_ref_svc.resolve_secret_for_key_id(
                    tenant_id=tenant_id,
                    purpose="audit_hmac",
                    key_id=key_id,
                )
                if resolved is not None:
                    secret = resolved.secret
            except Exception:  # pylint: disable=broad-except
                secret = None

        if secret is None:
            secret = self._config_secret_for_kid(key_id)

        key_cache[cache_key] = secret
        return secret

    @staticmethod
    def _scope_key(values: Mapping[str, Any]) -> str:
        tenant = values.get("tenant_id")
        tenant_token = str(tenant) if tenant is not None else "global"

        entity_set = str(values.get("entity_set", "")).strip().lower() or "unknown"
        return f"{tenant_token}:{entity_set}"

    @staticmethod
    def _same_datetime(left: datetime | None, right: datetime | None) -> bool:
        left_utc = AuditEventService._to_aware_utc(left)
        right_utc = AuditEventService._to_aware_utc(right)
        return left_utc == right_utc

    def _entry_hash_payload(self, row: Mapping[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for field in self._ENTRY_HASH_FIELDS:
            if field == "changed_fields":
                payload[field] = self._normalize_changed_fields(row.get(field))
                continue
            payload[field] = self._json_safe(row.get(field))
        return payload

    def _compute_entry_hash(self, row: Mapping[str, Any], *, secret: bytes) -> str:
        payload = self._entry_hash_payload(row)
        payload_bytes = self._canonical_json_bytes(payload)
        return hmac.new(secret, payload_bytes, digestmod=hashlib.sha256).hexdigest()

    async def _get_or_create_chain_head(
        self,
        *,
        uow: Any,
        scope_key: str,
    ) -> Mapping[str, Any]:
        head = await uow.get_one(_CHAIN_HEAD_TABLE, {"scope_key": scope_key})
        if head is not None:
            return head

        return await uow.insert(
            _CHAIN_HEAD_TABLE,
            {
                "scope_key": scope_key,
                "last_seq": 0,
                "last_entry_hash": _GENESIS_HASH,
            },
        )

    async def _update_chain_head(
        self,
        *,
        uow: Any,
        head: Mapping[str, Any],
        last_seq: int,
        last_entry_hash: str,
    ) -> Mapping[str, Any]:
        updated = await uow.update_one(
            _CHAIN_HEAD_TABLE,
            where={
                "id": head["id"],
                "row_version": head["row_version"],
            },
            changes={
                "last_seq": int(last_seq),
                "last_entry_hash": str(last_entry_hash),
            },
            returning=True,
        )
        if updated is None:
            raise RowVersionConflict(_CHAIN_HEAD_TABLE, {"id": head["id"]})
        return updated

    async def _insert_chained_event(
        self,
        *,
        row: dict[str, Any],
        hash_key_id: str,
        secret: bytes,
    ) -> AuditEventDE:
        last_error: Exception | None = None
        for _ in range(self._max_chain_retries):
            try:
                async with self._rsg.unit_of_work() as uow:
                    head = await self._get_or_create_chain_head(
                        uow=uow,
                        scope_key=row["scope_key"],
                    )
                    next_seq = int(head.get("last_seq") or 0) + 1
                    prev_hash = str(head.get("last_entry_hash") or _GENESIS_HASH)

                    insert_row = dict(row)
                    insert_row["scope_seq"] = next_seq
                    insert_row["prev_entry_hash"] = prev_hash
                    insert_row["hash_key_id"] = hash_key_id
                    insert_row["entry_hash"] = self._compute_entry_hash(
                        insert_row,
                        secret=secret,
                    )
                    insert_row["sealed_at"] = self._now_utc()

                    await self._update_chain_head(
                        uow=uow,
                        head=head,
                        last_seq=next_seq,
                        last_entry_hash=insert_row["entry_hash"],
                    )
                    inserted = await uow.insert(self.table, insert_row)
                    return self._from_record(inserted)
            except RowVersionConflict as exc:
                last_error = exc
                continue
            except IntegrityError as exc:
                msg = str(exc).lower()
                if (
                    "ux_audit_chain_head__scope_key" in msg
                    or "duplicate key value" in msg
                ):
                    last_error = exc
                    continue
                raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("Unable to append chained audit event.")

    async def create(self, values: Mapping[str, Any]) -> AuditEventDE:
        """Create an audit event and seal it into the per-scope hash chain."""
        row = dict(values)
        row.setdefault("id", uuid.uuid4())
        now = self._now_utc()

        occurred_at = self._to_aware_utc(row.get("occurred_at"))
        row["occurred_at"] = occurred_at or now

        row["scope_key"] = str(row.get("scope_key") or self._scope_key(row))
        row["changed_fields"] = self._normalize_changed_fields(
            row.get("changed_fields")
        )
        row["hash_alg"] = str(row.get("hash_alg") or "hmac-sha256")
        row["before_snapshot_hash"] = str(
            row.get("before_snapshot_hash")
            or self._snapshot_hash(row.get("before_snapshot"))
        )
        row["after_snapshot_hash"] = str(
            row.get("after_snapshot_hash")
            or self._snapshot_hash(row.get("after_snapshot"))
        )

        hash_key_id, secret = await self._active_hash_material(
            tenant_id=row.get("tenant_id"),
        )
        return await self._insert_chained_event(
            row=row,
            hash_key_id=hash_key_id,
            secret=secret,
        )

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> AuditEventDE:
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
            abort(404, "Audit event not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_action_row(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> AuditEventDE:
        try:
            updated = await self.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes=changes,
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Audit event not found.")

        return updated

    @staticmethod
    def _where_non_tenant_entity(entity_id: uuid.UUID) -> dict[str, Any]:
        return {"id": entity_id, "tenant_id": None}

    @staticmethod
    def _legal_hold_is_active(event: AuditEventDE, now: datetime) -> bool:
        if event.legal_hold_at is None:
            return False

        if event.legal_hold_released_at is not None:
            return False

        hold_until = AuditEventService._to_aware_utc(event.legal_hold_until)
        if hold_until is None:
            return True

        return hold_until > now

    def _default_purge_grace_days(self) -> int:
        lifecycle_cfg = getattr(self._audit_config(), "lifecycle", SimpleNamespace())
        raw = getattr(lifecycle_cfg, "purge_grace_days", 30)
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 30

    def _default_batch_size(self) -> int:
        lifecycle_cfg = getattr(self._audit_config(), "lifecycle", SimpleNamespace())
        raw = getattr(lifecycle_cfg, "batch_size_default", 100)
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return 100

    async def _place_legal_hold(
        self,
        *,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: Any,
    ) -> tuple[str, int]:
        event = await self._get_for_action(
            where=where,
            expected_row_version=int(data.row_version),
        )
        now = self._now_utc()
        until = self._to_aware_utc(getattr(data, "legal_hold_until", None))
        reason = self._normalize_optional_text(getattr(data, "reason", None))

        if reason is None:
            abort(400, "Reason must be non-empty.")

        if self._legal_hold_is_active(event, now):
            same_until = self._same_datetime(event.legal_hold_until, until)
            same_reason = (
                self._normalize_optional_text(event.legal_hold_reason) == reason
            )
            if same_until and same_reason:
                return "", 204
            abort(409, "Audit event is already on legal hold.")

        await self._update_action_row(
            where=where,
            expected_row_version=int(data.row_version),
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
        return "", 204

    async def _release_legal_hold(
        self,
        *,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: Any,
    ) -> tuple[str, int]:
        event = await self._get_for_action(
            where=where,
            expected_row_version=int(data.row_version),
        )
        now = self._now_utc()
        reason = self._normalize_optional_text(getattr(data, "reason", None))

        if reason is None:
            abort(400, "Reason must be non-empty.")

        if not self._legal_hold_is_active(event, now):
            return "", 204

        await self._update_action_row(
            where=where,
            expected_row_version=int(data.row_version),
            changes={
                "legal_hold_released_at": now,
                "legal_hold_released_by_user_id": auth_user_id,
                "legal_hold_release_reason": reason,
            },
        )
        return "", 204

    async def _redact_event(
        self,
        *,
        where: Mapping[str, Any],
        data: Any,
    ) -> tuple[str, int]:
        event = await self._get_for_action(
            where=where,
            expected_row_version=int(data.row_version),
        )
        now = self._now_utc()
        reason = self._normalize_optional_text(getattr(data, "reason", None))

        if reason is None:
            abort(400, "Reason must be non-empty.")

        if self._legal_hold_is_active(event, now):
            abort(409, "Audit event is on legal hold.")

        if event.redacted_at is not None:
            return "", 204

        await self._update_action_row(
            where=where,
            expected_row_version=int(data.row_version),
            changes={
                "before_snapshot": None,
                "after_snapshot": None,
                "redacted_at": now,
                "redaction_reason": reason,
            },
        )
        return "", 204

    async def _tombstone_event(
        self,
        *,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: Any,
    ) -> tuple[str, int]:
        event = await self._get_for_action(
            where=where,
            expected_row_version=int(data.row_version),
        )
        now = self._now_utc()
        reason = self._normalize_optional_text(getattr(data, "reason", None))

        if reason is None:
            abort(400, "Reason must be non-empty.")

        if self._legal_hold_is_active(event, now):
            abort(409, "Audit event is on legal hold.")

        if event.tombstoned_at is not None:
            return "", 204

        raw_days = getattr(data, "purge_after_days", None)
        if raw_days is None:
            purge_days = self._default_purge_grace_days()
        else:
            purge_days = max(0, int(raw_days))

        await self._update_action_row(
            where=where,
            expected_row_version=int(data.row_version),
            changes={
                "tombstoned_at": now,
                "tombstoned_by_user_id": auth_user_id,
                "tombstone_reason": reason,
                "purge_due_at": now + timedelta(days=purge_days),
            },
        )
        return "", 204

    async def entity_action_place_legal_hold(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: Any,
    ) -> tuple[str, int]:
        return await self._place_legal_hold(
            where=self._where_non_tenant_entity(entity_id),
            auth_user_id=auth_user_id,
            data=data,
        )

    async def action_place_legal_hold(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: Any,
    ) -> tuple[str, int]:
        return await self._place_legal_hold(
            where=where,
            auth_user_id=auth_user_id,
            data=data,
        )

    async def entity_action_release_legal_hold(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: Any,
    ) -> tuple[str, int]:
        return await self._release_legal_hold(
            where=self._where_non_tenant_entity(entity_id),
            auth_user_id=auth_user_id,
            data=data,
        )

    async def action_release_legal_hold(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: Any,
    ) -> tuple[str, int]:
        return await self._release_legal_hold(
            where=where,
            auth_user_id=auth_user_id,
            data=data,
        )

    async def entity_action_redact(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: Any,
    ) -> tuple[str, int]:
        return await self._redact_event(
            where=self._where_non_tenant_entity(entity_id),
            data=data,
        )

    async def action_redact(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: Any,
    ) -> tuple[str, int]:
        return await self._redact_event(
            where=where,
            data=data,
        )

    async def entity_action_tombstone(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: Any,
    ) -> tuple[str, int]:
        return await self._tombstone_event(
            where=self._where_non_tenant_entity(entity_id),
            auth_user_id=auth_user_id,
            data=data,
        )

    async def action_tombstone(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: Any,
    ) -> tuple[str, int]:
        return await self._tombstone_event(
            where=where,
            auth_user_id=auth_user_id,
            data=data,
        )

    @staticmethod
    def _tenant_base_where(
        *,
        tenant_id: uuid.UUID | None,
        non_tenant_only: bool,
    ) -> dict[str, Any]:
        if non_tenant_only:
            return {"tenant_id": None}
        if tenant_id is not None:
            return {"tenant_id": tenant_id}
        return {}

    async def _list_unsealed_rows(
        self,
        *,
        tenant_id: uuid.UUID | None,
        non_tenant_only: bool,
        limit: int,
    ) -> Sequence[AuditEventDE]:
        base = self._tenant_base_where(
            tenant_id=tenant_id,
            non_tenant_only=non_tenant_only,
        )
        filter_groups = [
            FilterGroup(where={**base, "sealed_at": None}),
            FilterGroup(where={**base, "entry_hash": None}),
            FilterGroup(where={**base, "scope_seq": None}),
        ]
        return await self.list(
            filter_groups=filter_groups,
            order_by=[
                OrderBy(field="occurred_at"),
                OrderBy(field="id"),
            ],
            limit=limit,
        )

    async def _count_unsealed_rows(
        self,
        *,
        tenant_id: uuid.UUID | None,
        non_tenant_only: bool,
    ) -> int:
        base = self._tenant_base_where(
            tenant_id=tenant_id,
            non_tenant_only=non_tenant_only,
        )
        return await self.count(
            filter_groups=[
                FilterGroup(where={**base, "sealed_at": None}),
                FilterGroup(where={**base, "entry_hash": None}),
                FilterGroup(where={**base, "scope_seq": None}),
            ]
        )

    async def _seal_existing_row(
        self,
        *,
        row_id: uuid.UUID,
        tenant_id: uuid.UUID | None,
        non_tenant_only: bool,
    ) -> bool:
        where = {"id": row_id}
        if non_tenant_only:
            where["tenant_id"] = None
        elif tenant_id is not None:
            where["tenant_id"] = tenant_id

        last_error: Exception | None = None

        for _ in range(self._max_chain_retries):
            try:
                async with self._rsg.unit_of_work() as uow:
                    row = await uow.get_one(self.table, where)
                    if row is None:
                        return False

                    if (
                        row.get("scope_seq") is not None
                        and row.get("entry_hash") is not None
                        and row.get("sealed_at") is not None
                    ):
                        return False

                    hash_key_id, secret = await self._active_hash_material(
                        tenant_id=row.get("tenant_id"),
                    )
                    row_version = int(row.get("row_version") or 0)
                    scope_key = str(row.get("scope_key") or self._scope_key(row))
                    before_hash = str(
                        row.get("before_snapshot_hash")
                        or self._snapshot_hash(row.get("before_snapshot"))
                    )
                    after_hash = str(
                        row.get("after_snapshot_hash")
                        or self._snapshot_hash(row.get("after_snapshot"))
                    )
                    hash_alg = str(row.get("hash_alg") or "hmac-sha256")

                    head = await self._get_or_create_chain_head(
                        uow=uow,
                        scope_key=scope_key,
                    )
                    next_seq = int(head.get("last_seq") or 0) + 1
                    prev_hash = str(head.get("last_entry_hash") or _GENESIS_HASH)

                    hash_row = dict(row)
                    hash_row["scope_key"] = scope_key
                    hash_row["scope_seq"] = next_seq
                    hash_row["prev_entry_hash"] = prev_hash
                    hash_row["hash_key_id"] = hash_key_id
                    hash_row["hash_alg"] = hash_alg
                    hash_row["before_snapshot_hash"] = before_hash
                    hash_row["after_snapshot_hash"] = after_hash
                    hash_row["entry_hash"] = self._compute_entry_hash(
                        hash_row,
                        secret=secret,
                    )

                    await self._update_chain_head(
                        uow=uow,
                        head=head,
                        last_seq=next_seq,
                        last_entry_hash=hash_row["entry_hash"],
                    )
                    updated = await uow.update_one(
                        self.table,
                        where={**where, "row_version": row_version},
                        changes={
                            "scope_key": scope_key,
                            "scope_seq": next_seq,
                            "prev_entry_hash": prev_hash,
                            "entry_hash": hash_row["entry_hash"],
                            "hash_alg": hash_alg,
                            "hash_key_id": hash_key_id,
                            "before_snapshot_hash": before_hash,
                            "after_snapshot_hash": after_hash,
                            "sealed_at": self._now_utc(),
                        },
                        returning=True,
                    )
                    if updated is None:
                        raise RowVersionConflict(self.table, where)
                    return True
            except RowVersionConflict as exc:
                last_error = exc
                continue
            except IntegrityError as exc:
                msg = str(exc).lower()
                if (
                    "ux_audit_chain_head__scope_key" in msg
                    or "duplicate key value" in msg
                ):
                    last_error = exc
                    continue
                raise

        if last_error is not None:
            raise last_error
        return False

    async def _seal_backlog_impl(
        self,
        *,
        tenant_id: uuid.UUID | None,
        non_tenant_only: bool,
        batch_size: int,
        max_batches: int,
        dry_run: bool,
    ) -> dict[str, Any]:
        rows_sealed = 0
        batches = 0

        for _ in range(max_batches):
            rows = await self._list_unsealed_rows(
                tenant_id=tenant_id,
                non_tenant_only=non_tenant_only,
                limit=batch_size,
            )
            if not rows:
                break

            batches += 1
            if dry_run:
                rows_sealed += len(rows)
                break

            batch_count = 0
            for row in rows:
                if row.id is None:
                    continue
                try:
                    did_seal = await self._seal_existing_row(
                        row_id=row.id,
                        tenant_id=tenant_id,
                        non_tenant_only=non_tenant_only,
                    )
                except RowVersionConflict:
                    continue
                except SQLAlchemyError:
                    continue

                if did_seal:
                    batch_count += 1
            rows_sealed += batch_count

            if batch_count == 0:
                break

        remaining = await self._count_unsealed_rows(
            tenant_id=tenant_id,
            non_tenant_only=non_tenant_only,
        )
        return {
            "RowsSealed": rows_sealed,
            "RemainingCount": remaining,
            "Batches": batches,
        }

    async def _phase_redact_due(
        self,
        *,
        tenant_id: uuid.UUID | None,
        non_tenant_only: bool,
        now: datetime,
        batch_size: int,
        max_batches: int,
        dry_run: bool,
    ) -> dict[str, Any]:
        rows_redacted = 0
        batches = 0
        base = self._tenant_base_where(
            tenant_id=tenant_id,
            non_tenant_only=non_tenant_only,
        )

        for _ in range(max_batches):
            rows = await self.list(
                filter_groups=[
                    FilterGroup(
                        where={**base, "redacted_at": None},
                        scalar_filters=[
                            ScalarFilter(
                                field="redaction_due_at",
                                op=ScalarFilterOp.LTE,
                                value=now,
                            ),
                        ],
                    )
                ],
                order_by=[OrderBy(field="occurred_at"), OrderBy(field="id")],
                limit=batch_size,
            )
            if not rows:
                break

            batches += 1
            batch_count = 0
            for row in rows:
                if row.id is None or row.row_version is None:
                    continue

                if self._legal_hold_is_active(row, now):
                    continue

                if dry_run:
                    batch_count += 1
                    continue

                try:
                    updated = await self.update_with_row_version(
                        where={"id": row.id},
                        expected_row_version=int(row.row_version),
                        changes={
                            "before_snapshot": None,
                            "after_snapshot": None,
                            "redacted_at": now,
                            "redaction_reason": "lifecycle:redact_due",
                        },
                    )
                except RowVersionConflict:
                    continue
                except SQLAlchemyError:
                    continue

                if updated is not None:
                    batch_count += 1

            rows_redacted += batch_count
            if batch_count == 0 or dry_run:
                break

        remaining = await self.count(
            filter_groups=[
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
        )
        return {
            "RowsProcessed": rows_redacted,
            "RemainingCount": remaining,
            "Batches": batches,
        }

    async def _phase_tombstone_expired(
        self,
        *,
        tenant_id: uuid.UUID | None,
        non_tenant_only: bool,
        now: datetime,
        batch_size: int,
        max_batches: int,
        dry_run: bool,
        purge_grace_days_override: int | None = None,
    ) -> dict[str, Any]:
        rows_tombstoned = 0
        batches = 0
        base = self._tenant_base_where(
            tenant_id=tenant_id,
            non_tenant_only=non_tenant_only,
        )
        grace_days = (
            self._default_purge_grace_days()
            if purge_grace_days_override is None
            else max(0, int(purge_grace_days_override))
        )

        for _ in range(max_batches):
            rows = await self.list(
                filter_groups=[
                    FilterGroup(
                        where={**base, "tombstoned_at": None},
                        scalar_filters=[
                            ScalarFilter(
                                field="retention_until",
                                op=ScalarFilterOp.LTE,
                                value=now,
                            ),
                        ],
                    )
                ],
                order_by=[OrderBy(field="occurred_at"), OrderBy(field="id")],
                limit=batch_size,
            )
            if not rows:
                break

            batches += 1
            batch_count = 0
            for row in rows:
                if row.id is None or row.row_version is None:
                    continue

                if self._legal_hold_is_active(row, now):
                    continue

                if dry_run:
                    batch_count += 1
                    continue

                try:
                    updated = await self.update_with_row_version(
                        where={"id": row.id},
                        expected_row_version=int(row.row_version),
                        changes={
                            "tombstoned_at": now,
                            "tombstone_reason": "lifecycle:retention_expired",
                            "purge_due_at": now + timedelta(days=grace_days),
                        },
                    )
                except RowVersionConflict:
                    continue
                except SQLAlchemyError:
                    continue

                if updated is not None:
                    batch_count += 1

            rows_tombstoned += batch_count
            if batch_count == 0 or dry_run:
                break

        remaining = await self.count(
            filter_groups=[
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
        )
        return {
            "RowsProcessed": rows_tombstoned,
            "RemainingCount": remaining,
            "Batches": batches,
        }

    async def _phase_purge_due(
        self,
        *,
        tenant_id: uuid.UUID | None,
        non_tenant_only: bool,
        now: datetime,
        batch_size: int,
        max_batches: int,
        dry_run: bool,
    ) -> dict[str, Any]:
        rows_purged = 0
        batches = 0
        base = self._tenant_base_where(
            tenant_id=tenant_id,
            non_tenant_only=non_tenant_only,
        )

        for _ in range(max_batches):
            rows = await self.list(
                filter_groups=[
                    FilterGroup(
                        where=base,
                        scalar_filters=[
                            ScalarFilter(
                                field="tombstoned_at",
                                op=ScalarFilterOp.NE,
                                value=None,
                            ),
                            ScalarFilter(
                                field="purge_due_at",
                                op=ScalarFilterOp.LTE,
                                value=now,
                            ),
                        ],
                    )
                ],
                order_by=[OrderBy(field="purge_due_at"), OrderBy(field="id")],
                limit=batch_size,
            )
            if not rows:
                break

            batches += 1
            batch_count = 0
            for row in rows:
                if row.id is None or row.row_version is None:
                    continue

                if self._legal_hold_is_active(row, now):
                    continue

                if dry_run:
                    batch_count += 1
                    continue

                try:
                    deleted = await self.delete_with_row_version(
                        {"id": row.id},
                        expected_row_version=int(row.row_version),
                    )
                except RowVersionConflict:
                    continue
                except SQLAlchemyError:
                    continue

                if deleted is not None:
                    batch_count += 1

            rows_purged += batch_count
            if batch_count == 0 or dry_run:
                break

        remaining = await self.count(
            filter_groups=[
                FilterGroup(
                    where=base,
                    scalar_filters=[
                        ScalarFilter(
                            field="tombstoned_at",
                            op=ScalarFilterOp.NE,
                            value=None,
                        ),
                        ScalarFilter(
                            field="purge_due_at",
                            op=ScalarFilterOp.LTE,
                            value=now,
                        ),
                    ],
                )
            ]
        )
        return {
            "RowsProcessed": rows_purged,
            "RemainingCount": remaining,
            "Batches": batches,
        }

    def _resolve_batch_size(self, value: Any) -> int:
        if value is None:
            return self._default_batch_size()
        return max(1, int(value))

    @staticmethod
    def _resolve_max_batches(value: Any) -> int:
        if value is None:
            return 1
        return max(1, int(value))

    @staticmethod
    def _resolve_optional_nonnegative_int(value: Any) -> int | None:
        if value is None:
            return None
        return max(0, int(value))

    @staticmethod
    def _resolve_phases(raw_phases: Sequence[str] | None) -> list[str]:
        phases = list(raw_phases or _DEFAULT_PHASES)
        seen: set[str] = set()
        ordered: list[str] = []
        for phase in phases:
            if phase not in _DEFAULT_PHASES:
                continue
            if phase in seen:
                continue
            seen.add(phase)
            ordered.append(phase)
        return ordered or list(_DEFAULT_PHASES)

    async def _run_lifecycle_impl(
        self,
        *,
        tenant_id: uuid.UUID | None,
        non_tenant_only: bool,
        data: Any,
    ) -> dict[str, Any]:
        batch_size = self._resolve_batch_size(getattr(data, "batch_size", None))
        max_batches = self._resolve_max_batches(getattr(data, "max_batches", None))
        dry_run = bool(getattr(data, "dry_run", False))
        purge_grace_days_override = self._resolve_optional_nonnegative_int(
            getattr(data, "purge_grace_days_override", None)
        )
        now = self._to_aware_utc(getattr(data, "now_override", None)) or self._now_utc()
        phases = self._resolve_phases(getattr(data, "phases", None))

        phase_results: dict[str, dict[str, Any]] = {}
        for phase in phases:
            if phase == "seal_backlog":
                phase_results[phase] = await self._seal_backlog_impl(
                    tenant_id=tenant_id,
                    non_tenant_only=non_tenant_only,
                    batch_size=batch_size,
                    max_batches=max_batches,
                    dry_run=dry_run,
                )
                continue

            if phase == "redact_due":
                phase_results[phase] = await self._phase_redact_due(
                    tenant_id=tenant_id,
                    non_tenant_only=non_tenant_only,
                    now=now,
                    batch_size=batch_size,
                    max_batches=max_batches,
                    dry_run=dry_run,
                )
                continue

            if phase == "tombstone_expired":
                phase_results[phase] = await self._phase_tombstone_expired(
                    tenant_id=tenant_id,
                    non_tenant_only=non_tenant_only,
                    now=now,
                    batch_size=batch_size,
                    max_batches=max_batches,
                    dry_run=dry_run,
                    purge_grace_days_override=purge_grace_days_override,
                )
                continue

            if phase == "purge_due":
                phase_results[phase] = await self._phase_purge_due(
                    tenant_id=tenant_id,
                    non_tenant_only=non_tenant_only,
                    now=now,
                    batch_size=batch_size,
                    max_batches=max_batches,
                    dry_run=dry_run,
                )
                continue

        total_processed = sum(
            int(result.get("RowsProcessed", result.get("RowsSealed", 0)))
            for result in phase_results.values()
        )
        return {
            "DryRun": dry_run,
            "Now": now.isoformat(),
            "BatchSize": batch_size,
            "MaxBatches": max_batches,
            "Phases": phase_results,
            "TotalProcessed": total_processed,
        }

    async def entity_set_action_run_lifecycle(
        self,
        *,
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: Any,
    ) -> tuple[dict[str, Any], int]:
        summary = await AuditLifecycleRunner(self).run_lifecycle(
            tenant_id=None,
            non_tenant_only=True,
            data=data,
        )
        return summary, 200

    async def action_run_lifecycle(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],  # noqa: ARG002
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: Any,
    ) -> tuple[dict[str, Any], int]:
        summary = await AuditLifecycleRunner(self).run_lifecycle(
            tenant_id=tenant_id,
            non_tenant_only=False,
            data=data,
        )
        return summary, 200

    async def _verify_chain_impl(
        self,
        *,
        tenant_id: uuid.UUID | None,
        non_tenant_only: bool,
        data: Any,
    ) -> dict[str, Any]:
        from_occurred_at = self._to_aware_utc(getattr(data, "from_occurred_at", None))
        to_occurred_at = self._to_aware_utc(getattr(data, "to_occurred_at", None))
        max_rows = int(getattr(data, "max_rows", 1000) or 1000)

        base_where = self._tenant_base_where(
            tenant_id=tenant_id,
            non_tenant_only=non_tenant_only,
        )
        scalar_filters: list[ScalarFilter] = []
        if from_occurred_at is not None:
            scalar_filters.append(
                ScalarFilter(
                    field="occurred_at",
                    op=ScalarFilterOp.GTE,
                    value=from_occurred_at,
                )
            )
        if to_occurred_at is not None:
            scalar_filters.append(
                ScalarFilter(
                    field="occurred_at",
                    op=ScalarFilterOp.LTE,
                    value=to_occurred_at,
                )
            )

        events = await self.list(
            filter_groups=[
                FilterGroup(
                    where=base_where,
                    scalar_filters=scalar_filters,
                )
            ],
            order_by=[
                OrderBy(field="scope_key"),
                OrderBy(field="scope_seq"),
                OrderBy(field="occurred_at"),
                OrderBy(field="id"),
            ],
            limit=max_rows,
        )

        chain_state: dict[str, dict[str, Any]] = {}
        mismatches: list[dict[str, Any]] = []
        secret_cache: dict[tuple[uuid.UUID | None, str], bytes | None] = {}
        checked = 0
        for event in events:
            checked += 1

            scope_key = str(event.scope_key or self._scope_key(event.__dict__))
            state = chain_state.setdefault(
                scope_key,
                {"last_seq": 0, "last_hash": _GENESIS_HASH},
            )
            expected_prev = str(state["last_hash"])
            expected_seq = int(state["last_seq"]) + 1

            reasons: list[str] = []
            if event.scope_seq is None or event.entry_hash is None:
                reasons.append("row_not_sealed")
            else:
                if int(event.scope_seq) != expected_seq:
                    reasons.append("scope_seq_mismatch")
                if str(event.prev_entry_hash or _GENESIS_HASH) != expected_prev:
                    reasons.append("prev_hash_mismatch")

                secret = await self._secret_for_kid(
                    tenant_id=event.tenant_id,
                    hash_key_id=event.hash_key_id,
                    key_cache=secret_cache,
                )
                if secret is None:
                    reasons.append("missing_hash_key")
                else:
                    computed_hash = self._compute_entry_hash(
                        event.__dict__,
                        secret=secret,
                    )
                    if str(event.entry_hash) != computed_hash:
                        reasons.append("entry_hash_mismatch")

            if reasons:
                if len(mismatches) < _MAX_CHAIN_MISMATCH_DETAILS:
                    mismatches.append(
                        {
                            "Id": str(event.id),
                            "ScopeKey": scope_key,
                            "ScopeSeq": event.scope_seq,
                            "Reasons": reasons,
                        }
                    )

            if event.scope_seq is not None and event.entry_hash is not None:
                state["last_seq"] = int(event.scope_seq)
                state["last_hash"] = str(event.entry_hash)

        is_valid = len(mismatches) == 0
        return {
            "IsValid": is_valid,
            "CheckedRows": checked,
            "MismatchCount": len(mismatches),
            "Mismatches": mismatches,
        }

    async def entity_set_action_verify_chain(
        self,
        *,
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: Any,
    ) -> tuple[dict[str, Any], int]:
        summary = await self._verify_chain_impl(
            tenant_id=None,
            non_tenant_only=True,
            data=data,
        )
        if bool(getattr(data, "require_clean", False)) and not summary["IsValid"]:
            abort(409, "Audit hash chain verification failed.")
        return summary, 200

    async def action_verify_chain(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],  # noqa: ARG002
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: Any,
    ) -> tuple[dict[str, Any], int]:
        summary = await self._verify_chain_impl(
            tenant_id=tenant_id,
            non_tenant_only=False,
            data=data,
        )
        if bool(getattr(data, "require_clean", False)) and not summary["IsValid"]:
            abort(409, "Audit hash chain verification failed.")
        return summary, 200

    async def entity_set_action_seal_backlog(
        self,
        *,
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: Any,
    ) -> tuple[dict[str, Any], int]:
        batch_size = self._resolve_batch_size(getattr(data, "batch_size", None))
        max_batches = self._resolve_max_batches(getattr(data, "max_batches", None))
        summary = await AuditLifecycleRunner(self).seal_backlog(
            tenant_id=None,
            non_tenant_only=True,
            batch_size=batch_size,
            max_batches=max_batches,
            dry_run=False,
        )
        summary["BatchSize"] = batch_size
        summary["MaxBatches"] = max_batches
        return summary, 200

    async def action_seal_backlog(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],  # noqa: ARG002
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: Any,
    ) -> tuple[dict[str, Any], int]:
        batch_size = self._resolve_batch_size(getattr(data, "batch_size", None))
        max_batches = self._resolve_max_batches(getattr(data, "max_batches", None))
        summary = await AuditLifecycleRunner(self).seal_backlog(
            tenant_id=tenant_id,
            non_tenant_only=False,
            batch_size=batch_size,
            max_batches=max_batches,
            dry_run=False,
        )
        summary["BatchSize"] = batch_size
        summary["MaxBatches"] = max_batches
        return summary, 200

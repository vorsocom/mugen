"""Provides a service for key reference registry operations."""

__all__ = ["KeyRefService"]

from datetime import datetime, timezone
import uuid
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup
from mugen.core.plugin.acp.constants import GLOBAL_TENANT_ID
from mugen.core.plugin.acp.contract.service.key_provider import ResolvedKeyMaterial
from mugen.core.plugin.acp.contract.service.key_ref import IKeyRefService
from mugen.core.plugin.acp.domain import KeyRefDE
from mugen.core.plugin.acp.service.key_provider import KeyMaterialResolver


class KeyRefService(
    IRelationalService[KeyRefDE],
    IKeyRefService,
):
    """CRUD + action workflow for `KeyRef` metadata and key resolution."""

    def __init__(
        self,
        table: str,
        rsg: IRelationalStorageGateway,
        key_material_resolver: KeyMaterialResolver | None = None,
        **kwargs,
    ):
        super().__init__(
            de_type=KeyRefDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._key_material_resolver = key_material_resolver or KeyMaterialResolver()

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_tenant_id(tenant_id: uuid.UUID | None) -> uuid.UUID:
        return tenant_id if tenant_id is not None else GLOBAL_TENANT_ID

    @staticmethod
    def _normalize_required_text(value: str | None, *, field_name: str) -> str:
        text = str(value or "").strip()
        if text == "":
            abort(400, f"{field_name} must be non-empty.")
        return text

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _normalize_provider(value: str | None) -> str:
        provider = str(value or "local").strip().lower()
        if provider == "":
            provider = "local"
        return provider

    @staticmethod
    def _status_text(value: Any) -> str:
        return str(getattr(value, "value", value) or "").strip()

    @classmethod
    def _status_lower(cls, value: Any) -> str:
        return cls._status_text(value).lower()

    async def create(self, values: Mapping[str, Any]) -> KeyRefDE:
        payload = dict(values)
        payload["tenant_id"] = self._normalize_tenant_id(payload.get("tenant_id"))
        payload["purpose"] = self._normalize_required_text(
            payload.get("purpose"),
            field_name="Purpose",
        )
        payload["key_id"] = self._normalize_required_text(
            payload.get("key_id"),
            field_name="KeyId",
        )
        payload["provider"] = self._normalize_provider(payload.get("provider"))
        if payload.get("status") is None:
            payload["status"] = "active"
        return await super().create(payload)

    async def _active_for_tenant(
        self,
        *,
        tenant_id: uuid.UUID,
        purpose: str,
    ) -> KeyRefDE | None:
        row = await self.get(
            {
                "tenant_id": tenant_id,
                "purpose": purpose,
                "status": "active",
            }
        )
        return row

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        not_found: str,
    ) -> KeyRefDE:
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

    async def _activate(
        self,
        *,
        tenant_id: uuid.UUID,
        purpose: str,
        key_id: str,
        provider: str,
        auth_user_id: uuid.UUID,
        attributes: dict[str, Any] | None,
    ) -> KeyRefDE:
        now = self._now_utc()

        existing_active = await self._active_for_tenant(
            tenant_id=tenant_id,
            purpose=purpose,
        )
        if (
            existing_active is not None
            and str(existing_active.key_id or "").lower() == key_id.lower()
            and str(existing_active.provider or "").lower() == provider.lower()
        ):
            return existing_active

        try:
            if existing_active is not None:
                await self.update(
                    {"id": existing_active.id},
                    {
                        "status": "retired",
                        "retired_at": now,
                        "retired_by_user_id": auth_user_id,
                        "retired_reason": "rotated",
                    },
                )

            candidate = await self.get(
                {
                    "tenant_id": tenant_id,
                    "purpose": purpose,
                    "key_id": key_id,
                }
            )
            if candidate is None:
                return await self.create(
                    {
                        "tenant_id": tenant_id,
                        "purpose": purpose,
                        "key_id": key_id,
                        "provider": provider,
                        "status": "active",
                        "activated_at": now,
                        "retired_at": None,
                        "retired_by_user_id": None,
                        "retired_reason": None,
                        "destroyed_at": None,
                        "destroyed_by_user_id": None,
                        "destroy_reason": None,
                        "attributes": attributes,
                    }
                )

            if candidate.status == "destroyed":
                abort(409, "Destroyed key references cannot be re-activated.")

            updated = await self.update(
                {"id": candidate.id},
                {
                    "provider": provider,
                    "status": "active",
                    "activated_at": now,
                    "retired_at": None,
                    "retired_by_user_id": None,
                    "retired_reason": None,
                    "destroyed_at": None,
                    "destroyed_by_user_id": None,
                    "destroy_reason": None,
                    "attributes": attributes,
                },
            )
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(409, "Key rotation could not be applied.")

        return updated

    async def _rotate(
        self,
        *,
        tenant_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: Any,
    ) -> tuple[dict[str, Any], int]:
        purpose = self._normalize_required_text(
            getattr(data, "purpose", None),
            field_name="Purpose",
        )
        key_id = self._normalize_required_text(
            getattr(data, "key_id", None),
            field_name="KeyId",
        )
        provider = self._normalize_provider(getattr(data, "provider", None))
        attributes = getattr(data, "attributes", None)

        row = await self._activate(
            tenant_id=tenant_id,
            purpose=purpose,
            key_id=key_id,
            provider=provider,
            auth_user_id=auth_user_id,
            attributes=attributes,
        )

        return {
            "Id": str(row.id),
            "TenantId": str(row.tenant_id),
            "Purpose": row.purpose,
            "KeyId": row.key_id,
            "Status": self._status_text(row.status),
        }, 200

    async def _retire(
        self,
        *,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: Any,
        not_found: str,
    ) -> tuple[dict[str, Any], int]:
        expected_row_version = int(getattr(data, "row_version"))
        row = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
            not_found=not_found,
        )

        if self._status_lower(row.status) == "destroyed":
            abort(409, "Destroyed key references cannot be retired.")

        if self._status_lower(row.status) == "retired":
            return {
                "Id": str(row.id),
                "Status": self._status_text(row.status),
            }, 200

        reason = self._normalize_optional_text(getattr(data, "reason", None))

        try:
            updated = await self.update_with_row_version(
                where={"id": row.id},
                expected_row_version=expected_row_version,
                changes={
                    "status": "retired",
                    "retired_at": self._now_utc(),
                    "retired_by_user_id": auth_user_id,
                    "retired_reason": reason,
                },
            )
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(409, "RowVersion conflict. Refresh and retry.")

        return {
            "Id": str(updated.id),
            "Status": self._status_text(updated.status),
        }, 200

    async def _destroy(
        self,
        *,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: Any,
        not_found: str,
    ) -> tuple[dict[str, Any], int]:
        expected_row_version = int(getattr(data, "row_version"))
        row = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
            not_found=not_found,
        )

        if self._status_lower(row.status) == "destroyed":
            return {
                "Id": str(row.id),
                "Status": self._status_text(row.status),
            }, 200

        reason = self._normalize_optional_text(getattr(data, "reason", None))
        now = self._now_utc()

        try:
            updated = await self.update_with_row_version(
                where={"id": row.id},
                expected_row_version=expected_row_version,
                changes={
                    "status": "destroyed",
                    "retired_at": row.retired_at or now,
                    "retired_by_user_id": row.retired_by_user_id or auth_user_id,
                    "retired_reason": row.retired_reason
                    or self._normalize_optional_text("destroyed"),
                    "destroyed_at": now,
                    "destroyed_by_user_id": auth_user_id,
                    "destroy_reason": reason,
                },
            )
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(409, "RowVersion conflict. Refresh and retry.")

        return {
            "Id": str(updated.id),
            "Status": self._status_text(updated.status),
        }, 200

    async def entity_set_action_rotate(
        self,
        *,
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[dict[str, Any], int]:
        tenant_id = self._normalize_tenant_id(getattr(data, "tenant_id", None))
        return await self._rotate(
            tenant_id=tenant_id,
            auth_user_id=auth_user_id,
            data=data,
        )

    async def action_rotate(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[dict[str, Any], int]:
        _ = where
        return await self._rotate(
            tenant_id=self._normalize_tenant_id(tenant_id),
            auth_user_id=auth_user_id,
            data=data,
        )

    async def entity_action_retire(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[dict[str, Any], int]:
        return await self._retire(
            where={"id": entity_id},
            auth_user_id=auth_user_id,
            data=data,
            not_found="Key reference not found.",
        )

    async def action_retire(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[dict[str, Any], int]:
        _ = where
        return await self._retire(
            where={"tenant_id": tenant_id, "id": entity_id},
            auth_user_id=auth_user_id,
            data=data,
            not_found="Key reference not found.",
        )

    async def entity_action_destroy(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[dict[str, Any], int]:
        return await self._destroy(
            where={"id": entity_id},
            auth_user_id=auth_user_id,
            data=data,
            not_found="Key reference not found.",
        )

    async def action_destroy(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[dict[str, Any], int]:
        _ = where
        return await self._destroy(
            where={"tenant_id": tenant_id, "id": entity_id},
            auth_user_id=auth_user_id,
            data=data,
            not_found="Key reference not found.",
        )

    async def resolve_active_for_purpose(
        self,
        *,
        tenant_id: uuid.UUID | None,
        purpose: str,
    ) -> KeyRefDE | None:
        normalized_purpose = self._normalize_required_text(
            purpose,
            field_name="Purpose",
        )

        normalized_tenant = self._normalize_tenant_id(tenant_id)
        if normalized_tenant != GLOBAL_TENANT_ID:
            tenant_row = await self._active_for_tenant(
                tenant_id=normalized_tenant,
                purpose=normalized_purpose,
            )
            if tenant_row is not None:
                return tenant_row

        return await self._active_for_tenant(
            tenant_id=GLOBAL_TENANT_ID,
            purpose=normalized_purpose,
        )

    async def resolve_secret_for_purpose(
        self,
        *,
        tenant_id: uuid.UUID | None,
        purpose: str,
    ) -> ResolvedKeyMaterial | None:
        active = await self.resolve_active_for_purpose(
            tenant_id=tenant_id,
            purpose=purpose,
        )
        if active is None:
            return None

        return self._key_material_resolver.resolve(active)

    async def _resolve_for_key_id_in_scope(
        self,
        *,
        tenant_id: uuid.UUID,
        purpose: str,
        key_id: str,
    ) -> KeyRefDE | None:
        key_id_folded = key_id.casefold()
        for status in ("active", "retired"):
            try:
                rows = await self.list(
                    filter_groups=[
                        FilterGroup(
                            where={
                                "tenant_id": tenant_id,
                                "purpose": purpose,
                                "status": status,
                            }
                        )
                    ]
                )
            except SQLAlchemyError:
                abort(500)

            for row in rows:
                if self._status_lower(row.status) not in {"active", "retired"}:
                    continue
                if str(row.key_id or "").strip().casefold() == key_id_folded:
                    return row

        return None

    async def resolve_secret_for_key_id(
        self,
        *,
        tenant_id: uuid.UUID | None,
        purpose: str,
        key_id: str,
    ) -> ResolvedKeyMaterial | None:
        normalized_purpose = self._normalize_required_text(
            purpose,
            field_name="Purpose",
        )
        normalized_key_id = self._normalize_required_text(
            key_id,
            field_name="KeyId",
        )

        normalized_tenant = self._normalize_tenant_id(tenant_id)
        resolved_ref = await self._resolve_for_key_id_in_scope(
            tenant_id=normalized_tenant,
            purpose=normalized_purpose,
            key_id=normalized_key_id,
        )
        if resolved_ref is None and normalized_tenant != GLOBAL_TENANT_ID:
            resolved_ref = await self._resolve_for_key_id_in_scope(
                tenant_id=GLOBAL_TENANT_ID,
                purpose=normalized_purpose,
                key_id=normalized_key_id,
            )

        if resolved_ref is None:
            return None
        return self._key_material_resolver.resolve(resolved_ref)

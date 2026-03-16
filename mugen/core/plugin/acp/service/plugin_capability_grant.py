"""Provides a service for plugin capability grant lifecycle operations."""

__all__ = ["PluginCapabilityGrantService"]

from datetime import datetime, timezone
import uuid
from typing import Any, Mapping, Sequence

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.constants import GLOBAL_TENANT_ID
from mugen.core.plugin.acp.contract.service.plugin_capability_grant import (
    IPluginCapabilityGrantService,
)
from mugen.core.plugin.acp.domain import PluginCapabilityGrantDE


class PluginCapabilityGrantService(
    IRelationalService[PluginCapabilityGrantDE],
    IPluginCapabilityGrantService,
):
    """CRUD + action workflow for runtime plugin capability grants."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=PluginCapabilityGrantDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

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
    def _normalize_capabilities(value: Any) -> list[str]:
        if not isinstance(value, Sequence) or isinstance(
            value, (str, bytes, bytearray)
        ):
            abort(400, "Capabilities must be a non-empty list.")

        output: list[str] = []
        seen: set[str] = set()
        for item in value:
            capability = str(item or "").strip().lower()
            if capability == "":
                continue
            if capability in seen:
                continue
            seen.add(capability)
            output.append(capability)

        if not output:
            abort(400, "Capabilities must include at least one value.")

        return output

    @staticmethod
    def _same_datetime(left: datetime | None, right: datetime | None) -> bool:
        if left is None and right is None:
            return True
        if left is None or right is None:
            return False

        left_utc = left
        if left_utc.tzinfo is None:
            left_utc = left_utc.replace(tzinfo=timezone.utc)

        right_utc = right
        if right_utc.tzinfo is None:
            right_utc = right_utc.replace(tzinfo=timezone.utc)

        return left_utc.astimezone(timezone.utc) == right_utc.astimezone(timezone.utc)

    async def create(self, values: Mapping[str, Any]) -> PluginCapabilityGrantDE:
        payload = dict(values)
        payload["tenant_id"] = self._normalize_tenant_id(payload.get("tenant_id"))
        payload["plugin_key"] = self._normalize_required_text(
            payload.get("plugin_key"),
            field_name="PluginKey",
        )
        payload["capabilities"] = self._normalize_capabilities(
            payload.get("capabilities") or []
        )
        return await super().create(payload)

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        not_found: str,
    ) -> PluginCapabilityGrantDE:
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

    @staticmethod
    def _is_expired(row: PluginCapabilityGrantDE, *, now: datetime) -> bool:
        expires_at = row.expires_at
        if expires_at is None:
            return False
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at.astimezone(timezone.utc) <= now

    async def _grant(
        self,
        *,
        tenant_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: Any,
    ) -> tuple[dict[str, Any], int]:
        plugin_key = self._normalize_required_text(
            getattr(data, "plugin_key", None),
            field_name="PluginKey",
        )
        capabilities = self._normalize_capabilities(getattr(data, "capabilities", []))
        expires_at = getattr(data, "expires_at", None)
        attributes = getattr(data, "attributes", None)
        now = self._now_utc()

        try:
            current = await self.get(
                {
                    "tenant_id": tenant_id,
                    "plugin_key": plugin_key,
                    "revoked_at": None,
                }
            )
        except SQLAlchemyError:
            abort(500)

        if current is not None:
            existing_capabilities = self._normalize_capabilities(
                current.capabilities or []
            )
            same_payload = (
                existing_capabilities == capabilities
                and self._same_datetime(current.expires_at, expires_at)
                and (current.attributes or None) == (attributes or None)
            )
            if same_payload:
                return {
                    "Id": str(current.id),
                    "TenantId": str(current.tenant_id),
                    "PluginKey": current.plugin_key,
                    "Granted": True,
                }, 200

            try:
                updated = await self.update(
                    {"id": current.id},
                    {
                        "capabilities": capabilities,
                        "granted_at": now,
                        "granted_by_user_id": auth_user_id,
                        "expires_at": expires_at,
                        "revoked_at": None,
                        "revoked_by_user_id": None,
                        "revoke_reason": None,
                        "attributes": attributes,
                    },
                )
            except SQLAlchemyError:
                abort(500)

            if updated is None:
                abort(409, "Capability grant could not be updated.")

            return {
                "Id": str(updated.id),
                "TenantId": str(updated.tenant_id),
                "PluginKey": updated.plugin_key,
                "Granted": True,
            }, 200

        created = await self.create(
            {
                "tenant_id": tenant_id,
                "plugin_key": plugin_key,
                "capabilities": capabilities,
                "granted_at": now,
                "granted_by_user_id": auth_user_id,
                "expires_at": expires_at,
                "attributes": attributes,
            }
        )

        return {
            "Id": str(created.id),
            "TenantId": str(created.tenant_id),
            "PluginKey": created.plugin_key,
            "Granted": True,
        }, 201

    async def _revoke(
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
            not_found="Capability grant not found.",
        )

        if row.revoked_at is not None:
            return {
                "Id": str(row.id),
                "Revoked": True,
            }, 200

        reason = self._normalize_optional_text(getattr(data, "reason", None))

        try:
            updated = await self.update_with_row_version(
                where={"id": row.id},
                expected_row_version=expected_row_version,
                changes={
                    "revoked_at": self._now_utc(),
                    "revoked_by_user_id": auth_user_id,
                    "revoke_reason": reason,
                },
            )
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(409, "RowVersion conflict. Refresh and retry.")

        return {
            "Id": str(updated.id),
            "Revoked": True,
        }, 200

    async def entity_set_action_grant(
        self,
        *,
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[dict[str, Any], int]:
        tenant_id = self._normalize_tenant_id(getattr(data, "tenant_id", None))
        return await self._grant(
            tenant_id=tenant_id,
            auth_user_id=auth_user_id,
            data=data,
        )

    async def action_grant(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[dict[str, Any], int]:
        _ = where
        return await self._grant(
            tenant_id=self._normalize_tenant_id(tenant_id),
            auth_user_id=auth_user_id,
            data=data,
        )

    async def entity_action_revoke(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[dict[str, Any], int]:
        return await self._revoke(
            where={"id": entity_id},
            auth_user_id=auth_user_id,
            data=data,
        )

    async def action_revoke(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data,
    ) -> tuple[dict[str, Any], int]:
        _ = where
        return await self._revoke(
            where={"tenant_id": tenant_id, "id": entity_id},
            auth_user_id=auth_user_id,
            data=data,
        )

    async def _resolve_for_tenant(
        self,
        *,
        tenant_id: uuid.UUID,
        plugin_key: str,
    ) -> PluginCapabilityGrantDE | None:
        row = await self.get(
            {
                "tenant_id": tenant_id,
                "plugin_key": plugin_key,
                "revoked_at": None,
            }
        )
        if row is None:
            return None

        if self._is_expired(row, now=self._now_utc()):
            return None

        return row

    async def resolve_capability(
        self,
        *,
        tenant_id: uuid.UUID | None,
        plugin_key: str,
        capability: str,
    ) -> tuple[bool, uuid.UUID | None, PluginCapabilityGrantDE | None]:
        normalized_plugin_key = self._normalize_required_text(
            plugin_key,
            field_name="PluginKey",
        )
        normalized_capability = self._normalize_required_text(
            capability,
            field_name="Capability",
        ).lower()
        normalized_tenant = self._normalize_tenant_id(tenant_id)

        if normalized_tenant != GLOBAL_TENANT_ID:
            tenant_row = await self._resolve_for_tenant(
                tenant_id=normalized_tenant,
                plugin_key=normalized_plugin_key,
            )
            if tenant_row is not None:
                granted = normalized_capability in self._normalize_capabilities(
                    tenant_row.capabilities or []
                )
                return granted, normalized_tenant, tenant_row

        global_row = await self._resolve_for_tenant(
            tenant_id=GLOBAL_TENANT_ID,
            plugin_key=normalized_plugin_key,
        )
        if global_row is None:
            return False, None, None

        granted = normalized_capability in self._normalize_capabilities(
            global_row.capabilities or []
        )
        return granted, GLOBAL_TENANT_ID, global_row

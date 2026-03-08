"""Provides a service for ACP-owned mixed-scope runtime config profiles."""

from __future__ import annotations

__all__ = ["RuntimeConfigProfileService"]

from typing import Any
import uuid

from quart import abort

from mugen.core import di
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.acp.constants import GLOBAL_TENANT_ID
from mugen.core.plugin.acp.domain import RuntimeConfigProfileDE
from mugen.core.plugin.acp.utility.runtime_config_policy import (
    normalize_runtime_config_category,
    normalize_runtime_config_profile_key,
    normalize_runtime_config_settings,
)
from mugen.core.service.platform_runtime_reload import reload_platform_runtime_profiles


class RuntimeConfigProfileService(
    IRelationalService[RuntimeConfigProfileDE],
):
    """CRUD + tenant/global fallback helpers for runtime config overlays."""

    def __init__(
        self,
        table: str,
        rsg: IRelationalStorageGateway,
        **kwargs,
    ) -> None:
        super().__init__(
            de_type=RuntimeConfigProfileDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    @staticmethod
    def _normalize_tenant_id(value: object) -> uuid.UUID:
        if value is None:
            return GLOBAL_TENANT_ID
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value).strip())
        except (AttributeError, TypeError, ValueError) as exc:
            raise RuntimeError("TenantId must be a valid UUID.") from exc

    @staticmethod
    def _normalize_optional_text(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _normalize_attributes(value: object) -> dict[str, Any] | None:
        if value is None:
            return None
        if isinstance(value, dict) is not True:
            raise RuntimeError("Attributes must be a JSON object.")
        return dict(value)

    async def _reload_runtime_profiles_for_category(
        self,
        *,
        category: str,
        profile_key: str,
    ) -> None:
        if category != "messaging.platform_defaults":
            return

        try:
            injector = di.container.build()
        except Exception:  # pylint: disable=broad-exception-caught
            return

        try:
            await reload_platform_runtime_profiles(
                injector=injector,
                platforms=(profile_key,),
            )
        except Exception:  # pylint: disable=broad-exception-caught
            return

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized_category = normalize_runtime_config_category(payload.get("category"))
        normalized_profile_key = normalize_runtime_config_profile_key(
            category=normalized_category,
            value=payload.get("profile_key"),
        )
        return {
            "tenant_id": self._normalize_tenant_id(payload.get("tenant_id")),
            "category": normalized_category,
            "profile_key": normalized_profile_key,
            "display_name": self._normalize_optional_text(payload.get("display_name")),
            "is_active": bool(payload.get("is_active", True)),
            "settings_json": normalize_runtime_config_settings(
                category=normalized_category,
                profile_key=normalized_profile_key,
                value=payload.get("settings_json"),
            ),
            "attributes": self._normalize_attributes(payload.get("attributes")),
        }

    async def create(self, values: dict[str, Any]) -> RuntimeConfigProfileDE:
        try:
            payload = self._normalize_payload(dict(values))
        except RuntimeError as exc:
            abort(400, str(exc))
        created = await super().create(payload)
        await self._reload_runtime_profiles_for_category(
            category=payload["category"],
            profile_key=payload["profile_key"],
        )
        return created

    async def update(
        self,
        where: dict[str, Any],
        changes: dict[str, Any],
    ) -> RuntimeConfigProfileDE | None:
        current = await self.get(where)
        if current is None:
            return None

        try:
            payload = self._normalize_payload(
                {
                    "tenant_id": changes.get("tenant_id", current.tenant_id),
                    "category": changes.get("category", current.category),
                    "profile_key": changes.get("profile_key", current.profile_key),
                    "display_name": changes.get("display_name", current.display_name),
                    "is_active": changes.get("is_active", current.is_active),
                    "settings_json": changes.get(
                        "settings_json",
                        current.settings_json or {},
                    ),
                    "attributes": changes.get("attributes", current.attributes),
                }
            )
        except RuntimeError as exc:
            abort(400, str(exc))
        updated = await super().update(where, payload)
        if updated is not None:
            await self._reload_runtime_profiles_for_category(
                category=payload["category"],
                profile_key=payload["profile_key"],
            )
        return updated

    async def update_with_row_version(
        self,
        where: dict[str, Any],
        *,
        expected_row_version: int,
        changes: dict[str, Any],
    ) -> RuntimeConfigProfileDE | None:
        current = await self.get(where)
        if current is None:
            return None

        try:
            payload = self._normalize_payload(
                {
                    "tenant_id": changes.get("tenant_id", current.tenant_id),
                    "category": changes.get("category", current.category),
                    "profile_key": changes.get("profile_key", current.profile_key),
                    "display_name": changes.get("display_name", current.display_name),
                    "is_active": changes.get("is_active", current.is_active),
                    "settings_json": changes.get(
                        "settings_json",
                        current.settings_json or {},
                    ),
                    "attributes": changes.get("attributes", current.attributes),
                }
            )
        except RuntimeError as exc:
            abort(400, str(exc))
        updated = await super().update_with_row_version(
            where,
            expected_row_version=expected_row_version,
            changes=payload,
        )
        if updated is not None:
            await self._reload_runtime_profiles_for_category(
                category=payload["category"],
                profile_key=payload["profile_key"],
            )
        return updated

    async def resolve_active_profile(
        self,
        *,
        tenant_id: uuid.UUID | None,
        category: str,
        profile_key: str,
    ) -> RuntimeConfigProfileDE | None:
        normalized_tenant = self._normalize_tenant_id(tenant_id)
        normalized_category = normalize_runtime_config_category(category)
        normalized_profile_key = normalize_runtime_config_profile_key(
            category=normalized_category,
            value=profile_key,
        )

        if normalized_tenant != GLOBAL_TENANT_ID:
            tenant_row = await self.get(
                {
                    "tenant_id": normalized_tenant,
                    "category": normalized_category,
                    "profile_key": normalized_profile_key,
                    "is_active": True,
                }
            )
            if tenant_row is not None:
                return tenant_row

        return await self.get(
            {
                "tenant_id": GLOBAL_TENANT_ID,
                "category": normalized_category,
                "profile_key": normalized_profile_key,
                "is_active": True,
            }
        )

    async def resolve_active_settings(
        self,
        *,
        tenant_id: uuid.UUID | None,
        category: str,
        profile_key: str,
    ) -> dict[str, Any]:
        profile = await self.resolve_active_profile(
            tenant_id=tenant_id,
            category=category,
            profile_key=profile_key,
        )
        if profile is None:
            return {}
        return normalize_runtime_config_settings(
            category=profile.category,
            profile_key=profile.profile_key,
            value=profile.settings_json,
        )

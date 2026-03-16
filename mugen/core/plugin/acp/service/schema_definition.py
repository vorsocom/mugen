"""Provides a service for the SchemaDefinition declarative model."""

__all__ = ["SchemaDefinitionService"]

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core import di
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup
from mugen.core.plugin.acp.constants import GLOBAL_TENANT_ID
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.contract.service.schema_definition import (
    ISchemaDefinitionService,
)
from mugen.core.plugin.acp.domain import SchemaDefinitionDE
from mugen.core.plugin.acp.utility.schema_json import (
    apply_json_schema_defaults,
    checksum_sha256,
    json_size_bytes,
    validate_json_schema_payload,
)

_DEFAULT_MAX_SCHEMA_BYTES = 256 * 1024


def _config_provider():
    return di.container.config


class SchemaDefinitionService(
    IRelationalService[SchemaDefinitionDE],
    ISchemaDefinitionService,
):
    """A service for ACP schema definitions."""

    def __init__(
        self,
        table: str,
        rsg: IRelationalStorageGateway,
        config_provider=_config_provider,
        **kwargs,
    ):
        super().__init__(
            de_type=SchemaDefinitionDE,
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
    def _normalize_key(key: str | None) -> str:
        normalized = (key or "").strip()
        if normalized == "":
            abort(400, "Key must be non-empty.")
        return normalized

    def _schema_registry_cfg(self) -> SimpleNamespace:
        config = self._config_provider()
        acp_cfg = getattr(config, "acp", SimpleNamespace())
        return getattr(acp_cfg, "schema_registry", SimpleNamespace())

    def _max_schema_bytes(self) -> int:
        cfg = self._schema_registry_cfg()
        raw = getattr(cfg, "max_schema_bytes", None)
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            return _DEFAULT_MAX_SCHEMA_BYTES
        if parsed <= 0:
            return _DEFAULT_MAX_SCHEMA_BYTES
        return parsed

    def _require_json_schema(self, definition: SchemaDefinitionDE) -> dict[str, Any]:
        schema_kind = str(definition.schema_kind or "json_schema").strip().lower()
        if schema_kind != "json_schema":
            abort(400, f"Unsupported schema kind: {definition.schema_kind!r}.")

        schema_json = definition.schema_json
        if not isinstance(schema_json, Mapping):
            abort(400, "Schema JSON must be an object.")

        return {str(k): v for k, v in schema_json.items()}

    async def create(self, values: Mapping[str, Any]) -> SchemaDefinitionDE:
        """Create schema definition with checksum and size validation."""
        payload = dict(values)
        if "schema_json" not in payload and "schema_payload" in payload:
            payload["schema_json"] = payload.pop("schema_payload")

        schema_json = payload.get("schema_json")
        if not isinstance(schema_json, Mapping):
            abort(400, "SchemaJson must be an object.")

        max_schema_bytes = self._max_schema_bytes()
        schema_bytes = json_size_bytes(schema_json)
        if schema_bytes > max_schema_bytes:
            abort(
                413,
                (
                    "SchemaJson exceeds configured max_schema_bytes "
                    f"({schema_bytes} > {max_schema_bytes})."
                ),
            )

        payload["tenant_id"] = self._normalize_tenant_id(payload.get("tenant_id"))
        payload["key"] = self._normalize_key(payload.get("key"))

        if payload.get("version") is None:
            abort(400, "Version is required.")

        payload["schema_kind"] = str(
            payload.get("schema_kind") or "json_schema"
        ).strip()
        if payload["schema_kind"] == "":
            payload["schema_kind"] = "json_schema"

        if payload.get("status") is None:
            payload["status"] = "draft"

        computed_checksum = checksum_sha256(schema_json)
        provided_checksum = (payload.get("checksum_sha256") or "").strip()
        if provided_checksum and provided_checksum != computed_checksum:
            abort(409, "ChecksumSha256 does not match SchemaJson content.")

        payload["checksum_sha256"] = computed_checksum

        return await super().create(payload)

    async def _resolve_definition(
        self,
        *,
        tenant_id: uuid.UUID | None,
        schema_definition_id: uuid.UUID | None,
        key: str | None,
        version: int | None,
    ) -> SchemaDefinitionDE:
        normalized_tenant_id = self._normalize_tenant_id(tenant_id)

        where: dict[str, Any]
        if schema_definition_id is not None:
            where = {
                "id": schema_definition_id,
                "tenant_id": normalized_tenant_id,
            }
        else:
            if version is None:
                abort(400, "Version is required when SchemaDefinitionId is omitted.")
            where = {
                "tenant_id": normalized_tenant_id,
                "key": self._normalize_key(key),
                "version": int(version),
            }

        definition = await self.get(where)
        if definition is None:
            abort(404, "Schema definition not found.")

        return definition

    async def validate_payload(
        self,
        *,
        tenant_id: uuid.UUID | None,
        schema_definition_id: uuid.UUID | None,
        key: str | None,
        version: int | None,
        payload: Any,
    ) -> tuple[SchemaDefinitionDE, list[str]]:
        """Validate payload against a referenced schema definition."""
        definition = await self._resolve_definition(
            tenant_id=tenant_id,
            schema_definition_id=schema_definition_id,
            key=key,
            version=version,
        )

        schema_json = self._require_json_schema(definition)
        errors = validate_json_schema_payload(
            schema=schema_json,
            payload=payload,
        )
        return definition, errors

    async def coerce_payload(
        self,
        *,
        tenant_id: uuid.UUID | None,
        schema_definition_id: uuid.UUID | None,
        key: str | None,
        version: int | None,
        payload: Any,
    ) -> tuple[SchemaDefinitionDE, Any, list[str]]:
        """Apply defaults and validate payload against a schema definition."""
        definition = await self._resolve_definition(
            tenant_id=tenant_id,
            schema_definition_id=schema_definition_id,
            key=key,
            version=version,
        )

        schema_json = self._require_json_schema(definition)
        coerced = apply_json_schema_defaults(
            schema=schema_json,
            payload=payload,
        )
        errors = validate_json_schema_payload(
            schema=schema_json,
            payload=coerced,
        )
        return definition, coerced, errors

    async def activate_version(
        self,
        *,
        tenant_id: uuid.UUID | None,
        key: str,
        version: int,
        activated_by_user_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Activate a schema version and deactivate prior active versions."""
        normalized_tenant_id = self._normalize_tenant_id(tenant_id)
        normalized_key = self._normalize_key(key)

        target = await self.get(
            {
                "tenant_id": normalized_tenant_id,
                "key": normalized_key,
                "version": int(version),
            }
        )
        if target is None:
            abort(404, "Schema definition not found.")

        now = self._now_utc()

        try:
            async with self._rsg.unit_of_work() as uow:
                rows = await uow.find(
                    self.table,
                    filter_groups=[
                        FilterGroup(
                            where={
                                "tenant_id": normalized_tenant_id,
                                "key": normalized_key,
                            }
                        )
                    ],
                )

                for row in rows:
                    if row.get("id") == target.id:
                        await uow.update_one(
                            self.table,
                            where={"id": target.id},
                            changes={
                                "status": "active",
                                "activated_at": now,
                                "activated_by_user_id": activated_by_user_id,
                            },
                            returning=False,
                        )
                        continue

                    if row.get("status") != "active":
                        continue

                    await uow.update_one(
                        self.table,
                        where={"id": row.get("id")},
                        changes={
                            "status": "inactive",
                            "activated_at": None,
                            "activated_by_user_id": None,
                        },
                        returning=False,
                    )
        except SQLAlchemyError:
            abort(500)

        return {
            "TenantId": str(normalized_tenant_id),
            "Key": normalized_key,
            "Version": int(version),
            "Status": "active",
        }

    async def entity_set_action_validate(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Validate payload against a schema reference."""
        _ = auth_user_id
        definition, errors = await self.validate_payload(
            tenant_id=getattr(data, "tenant_id", None),
            schema_definition_id=getattr(data, "schema_definition_id", None),
            key=getattr(data, "key", None),
            version=getattr(data, "version", None),
            payload=getattr(data, "payload", None),
        )
        return {
            "SchemaDefinitionId": str(definition.id),
            "Valid": len(errors) == 0,
            "Errors": errors,
        }, 200

    async def action_validate(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Validate payload for tenant-scoped requests."""
        _ = where
        _ = auth_user_id
        definition, errors = await self.validate_payload(
            tenant_id=tenant_id,
            schema_definition_id=getattr(data, "schema_definition_id", None),
            key=getattr(data, "key", None),
            version=getattr(data, "version", None),
            payload=getattr(data, "payload", None),
        )
        return {
            "SchemaDefinitionId": str(definition.id),
            "Valid": len(errors) == 0,
            "Errors": errors,
        }, 200

    async def entity_set_action_coerce(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Apply defaults and validate payload against a schema reference."""
        _ = auth_user_id
        definition, coerced, errors = await self.coerce_payload(
            tenant_id=getattr(data, "tenant_id", None),
            schema_definition_id=getattr(data, "schema_definition_id", None),
            key=getattr(data, "key", None),
            version=getattr(data, "version", None),
            payload=getattr(data, "payload", None),
        )
        return {
            "SchemaDefinitionId": str(definition.id),
            "Valid": len(errors) == 0,
            "CoercedPayload": coerced,
            "Errors": errors,
        }, 200

    async def action_coerce(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Apply defaults and validate payload for tenant-scoped requests."""
        _ = where
        _ = auth_user_id
        definition, coerced, errors = await self.coerce_payload(
            tenant_id=tenant_id,
            schema_definition_id=getattr(data, "schema_definition_id", None),
            key=getattr(data, "key", None),
            version=getattr(data, "version", None),
            payload=getattr(data, "payload", None),
        )
        return {
            "SchemaDefinitionId": str(definition.id),
            "Valid": len(errors) == 0,
            "CoercedPayload": coerced,
            "Errors": errors,
        }, 200

    async def entity_set_action_activate_version(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Activate a schema version."""
        payload = await self.activate_version(
            tenant_id=getattr(data, "tenant_id", None),
            key=getattr(data, "key", None),
            version=int(getattr(data, "version", 0)),
            activated_by_user_id=auth_user_id,
        )
        return payload, 200

    async def action_activate_version(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Activate a tenant-scoped schema version."""
        _ = where
        payload = await self.activate_version(
            tenant_id=tenant_id,
            key=getattr(data, "key", None),
            version=int(getattr(data, "version", 0)),
            activated_by_user_id=auth_user_id,
        )
        return payload, 200

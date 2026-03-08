"""Provides a service for ACP-owned messaging client profiles."""

from __future__ import annotations

__all__ = [
    "MessagingClientProfileService",
    "RuntimeMessagingClientProfileSpec",
]

import copy
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
import uuid

from mugen.core import di
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup, OrderBy
from mugen.core.plugin.acp.constants import GLOBAL_TENANT_ID
from mugen.core.plugin.acp.domain import MessagingClientProfileDE
from mugen.core.plugin.acp.service.key_ref import KeyRefService
from mugen.core.service.platform_runtime_reload import reload_platform_runtime_profiles
from mugen.core.utility.platform_runtime_profile import build_config_namespace

_TABLE_KEY_REF = "admin_key_ref"

_ALLOWED_PLATFORMS = frozenset(
    {
        "line",
        "matrix",
        "signal",
        "telegram",
        "wechat",
        "whatsapp",
    }
)

_IDENTIFIER_COLUMNS = {
    "path_token": "path_token",
    "recipient_user_id": "recipient_user_id",
    "account_number": "account_number",
    "phone_number_id": "phone_number_id",
    "provider": "provider",
}

_IDENTIFIER_PATHS: dict[str, dict[str, tuple[str, ...]]] = {
    "line": {
        "path_token": ("webhook", "path_token"),
    },
    "matrix": {
        "recipient_user_id": ("client", "user"),
    },
    "signal": {
        "account_number": ("account", "number"),
    },
    "telegram": {
        "path_token": ("webhook", "path_token"),
    },
    "wechat": {
        "path_token": ("webhook", "path_token"),
        "provider": ("provider",),
    },
    "whatsapp": {
        "path_token": ("webhook", "path_token"),
        "phone_number_id": ("business", "phone_number_id"),
    },
}

_REQUIRED_IDENTIFIER_FIELDS: dict[str, tuple[str, ...]] = {
    "line": ("path_token",),
    "matrix": ("recipient_user_id",),
    "signal": ("account_number",),
    "telegram": ("path_token",),
    "wechat": ("path_token", "provider"),
    "whatsapp": ("path_token", "phone_number_id"),
}

_LEGACY_PLATFORM_FIELD_PATHS: dict[str, tuple[tuple[str, ...], ...]] = {
    "line": (
        ("channel",),
        ("webhook", "path_token"),
    ),
    "matrix": (
        ("assistant", "name"),
        ("client",),
        ("homeserver",),
        ("profile_displayname",),
        ("room_id",),
    ),
    "signal": (
        ("account",),
        ("api", "base_url"),
        ("api", "bearer_token"),
    ),
    "telegram": (
        ("bot",),
        ("webhook", "path_token"),
        ("webhook", "secret_token"),
    ),
    "wechat": (
        ("official_account",),
        ("provider",),
        ("wecom",),
        ("webhook", "aes_enabled"),
        ("webhook", "aes_key"),
        ("webhook", "path_token"),
        ("webhook", "signature_token"),
    ),
    "whatsapp": (
        ("app",),
        ("business",),
        ("graphapi", "access_token"),
        ("webhook", "path_token"),
        ("webhook", "verification_token"),
    ),
}


@dataclass(frozen=True, slots=True)
class RuntimeMessagingClientProfileSpec:
    """Resolved runtime config material for one ACP client profile."""

    client_profile_id: uuid.UUID
    tenant_id: uuid.UUID
    platform_key: str
    profile_key: str
    config: SimpleNamespace
    snapshot: dict[str, Any]


class MessagingClientProfileService(
    IRelationalService[MessagingClientProfileDE],
):
    """CRUD + runtime helpers for ACP-owned messaging client profiles."""

    def __init__(
        self,
        table: str,
        rsg: IRelationalStorageGateway,
        key_ref_service: KeyRefService | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            de_type=MessagingClientProfileDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._key_ref_service = key_ref_service or KeyRefService(
            table=_TABLE_KEY_REF,
            rsg=rsg,
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

    @classmethod
    def _normalize_required_text(cls, value: object, *, field_name: str) -> str:
        normalized = cls._normalize_optional_text(value)
        if normalized is None:
            raise RuntimeError(f"{field_name} must be non-empty.")
        return normalized

    @staticmethod
    def _normalize_mapping(value: object) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise RuntimeError("Expected a JSON object payload.")
        return dict(value)

    @staticmethod
    def _plain_data(value: Any) -> Any:
        if isinstance(value, SimpleNamespace):
            raw = getattr(value, "dict", None)
            if isinstance(raw, dict):
                return copy.deepcopy(raw)

            output: dict[str, Any] = {}
            for key, item in vars(value).items():
                if key == "dict" or key.endswith("__"):
                    continue
                output[key] = MessagingClientProfileService._plain_data(item)
            return output

        if isinstance(value, dict):
            return {
                str(key): MessagingClientProfileService._plain_data(item)
                for key, item in value.items()
            }

        if isinstance(value, list):
            return [MessagingClientProfileService._plain_data(item) for item in value]

        return copy.deepcopy(value)

    @staticmethod
    def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
        merged = copy.deepcopy(base)
        for key, value in overlay.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = MessagingClientProfileService._deep_merge(
                    dict(merged[key]),
                    value,
                )
                continue
            merged[key] = copy.deepcopy(value)
        return merged

    @staticmethod
    def _set_nested(payload: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
        current = payload
        for part in path[:-1]:
            node = current.get(part)
            if not isinstance(node, dict):
                node = {}
                current[part] = node
            current = node
        current[path[-1]] = value

    @staticmethod
    def _delete_nested(payload: dict[str, Any], path: tuple[str, ...]) -> None:
        current = payload
        parents: list[tuple[dict[str, Any], str]] = []
        for part in path[:-1]:
            next_node = current.get(part)
            if not isinstance(next_node, dict):
                return
            parents.append((current, part))
            current = next_node
        leaf_key = path[-1]
        if leaf_key not in current:
            return
        del current[leaf_key]
        while parents and current == {}:
            parent, parent_key = parents.pop()
            del parent[parent_key]
            current = parent

    @classmethod
    def _scrub_legacy_runtime_fields(
        cls,
        *,
        platform_key: str,
        platform_section: dict[str, Any],
    ) -> dict[str, Any]:
        scrubbed = copy.deepcopy(platform_section)
        scrubbed.pop("profiles", None)
        for path in _LEGACY_PLATFORM_FIELD_PATHS.get(platform_key, ()):
            cls._delete_nested(scrubbed, path)
        return scrubbed

    @classmethod
    def _normalize_platform_key(cls, value: object) -> str:
        platform_key = cls._normalize_required_text(value, field_name="PlatformKey")
        platform_key = platform_key.lower()
        if platform_key not in _ALLOWED_PLATFORMS:
            raise RuntimeError(
                "PlatformKey must be one of "
                f"{', '.join(sorted(_ALLOWED_PLATFORMS))}."
            )
        return platform_key

    @classmethod
    def _normalize_secret_refs(cls, value: object) -> dict[str, str]:
        payload = cls._normalize_mapping(value)
        normalized: dict[str, str] = {}
        for raw_key, raw_value in payload.items():
            key = cls._normalize_required_text(raw_key, field_name="SecretRefs key")
            try:
                normalized[key] = str(uuid.UUID(str(raw_value).strip()))
            except (AttributeError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"SecretRefs.{key} must be a valid KeyRef UUID."
                ) from exc
        return normalized

    def _normalize_identifier_fields(
        self,
        *,
        payload: dict[str, Any],
        platform_key: str,
    ) -> None:
        for field_name in _IDENTIFIER_COLUMNS.values():
            payload[field_name] = self._normalize_optional_text(payload.get(field_name))

        for field_name in _REQUIRED_IDENTIFIER_FIELDS.get(platform_key, ()):
            if payload.get(field_name) is None:
                raise RuntimeError(
                    f"{field_name} is required for platform {platform_key!r}."
                )

    async def _validate_secret_refs(
        self,
        *,
        tenant_id: uuid.UUID,
        secret_refs: dict[str, str],
    ) -> None:
        for key_ref_id in secret_refs.values():
            key_ref = await self._key_ref_service.get(
                {
                    "tenant_id": tenant_id,
                    "id": uuid.UUID(key_ref_id),
                    "status": "active",
                }
            )
            if key_ref is None:
                raise RuntimeError(
                    "SecretRefs must reference active KeyRefs in the same tenant."
                )

    async def _reload_runtime_profiles(self) -> None:
        await self._reload_runtime_profiles_for_platforms()

    async def _reload_runtime_profiles_for_platforms(
        self,
        *platform_keys: object,
    ) -> None:
        try:
            injector = di.container.build()
        except Exception:  # pylint: disable=broad-exception-caught
            return

        normalized_platforms: list[str] = []
        for raw_platform_key in platform_keys:
            try:
                normalized_platforms.append(
                    self._normalize_platform_key(raw_platform_key)
                )
            except RuntimeError:
                continue

        try:
            await reload_platform_runtime_profiles(
                injector=injector,
                platforms=tuple(dict.fromkeys(normalized_platforms)) or None,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            return

    @classmethod
    def _snapshot_for_runtime(
        cls,
        client_profile: MessagingClientProfileDE,
    ) -> dict[str, Any]:
        return {
            "id": str(client_profile.id),
            "tenant_id": str(client_profile.tenant_id),
            "platform_key": client_profile.platform_key,
            "profile_key": client_profile.profile_key,
            "display_name": client_profile.display_name,
            "is_active": bool(client_profile.is_active),
            "settings": cls._plain_data(client_profile.settings or {}),
            "secret_refs": dict(client_profile.secret_refs or {}),
            "path_token": client_profile.path_token,
            "recipient_user_id": client_profile.recipient_user_id,
            "account_number": client_profile.account_number,
            "phone_number_id": client_profile.phone_number_id,
            "provider": client_profile.provider,
        }

    async def _resolve_secret_value(
        self,
        *,
        tenant_id: uuid.UUID,
        key_ref_id: str,
    ) -> str:
        resolved = await self._key_ref_service.resolve_secret_for_id(
            tenant_id=tenant_id,
            key_ref_id=uuid.UUID(key_ref_id),
        )
        if resolved is None:
            raise RuntimeError("Unable to resolve KeyRef secret material.")
        return resolved.secret.decode("utf-8")

    async def build_runtime_platform_section(
        self,
        *,
        config: dict[str, Any] | SimpleNamespace,
        client_profile: MessagingClientProfileDE,
    ) -> dict[str, Any]:
        root = self._plain_data(config)
        if not isinstance(root, dict):
            raise TypeError("Configuration root must be a mapping.")

        platform_key = str(client_profile.platform_key or "").strip().lower()
        base_section = root.get(platform_key)
        if not isinstance(base_section, dict):
            base_section = {}
        else:
            base_section = self._scrub_legacy_runtime_fields(
                platform_key=platform_key,
                platform_section=base_section,
            )

        merged = self._deep_merge(
            base_section,
            self._plain_data(client_profile.settings or {}),
        )

        for identifier_type, path in _IDENTIFIER_PATHS.get(platform_key, {}).items():
            field_name = _IDENTIFIER_COLUMNS[identifier_type]
            value = getattr(client_profile, field_name, None)
            if value is not None:
                self._set_nested(merged, path, value)

        secret_refs = dict(client_profile.secret_refs or {})
        for dotted_path, key_ref_id in secret_refs.items():
            path = tuple(
                part.strip()
                for part in str(dotted_path).split(".")
                if part.strip() != ""
            )
            if not path:
                continue
            self._set_nested(
                merged,
                path,
                await self._resolve_secret_value(
                    tenant_id=client_profile.tenant_id,
                    key_ref_id=key_ref_id,
                ),
            )

        if platform_key == "matrix":
            self._delete_nested(merged, ("assistant", "name"))
            self._delete_nested(merged, ("profile_displayname",))
            display_name = self._normalize_optional_text(client_profile.display_name)
            if display_name is not None:
                merged["profile_displayname"] = display_name

        merged["key"] = str(client_profile.profile_key or "").strip()
        merged["client_profile_id"] = str(client_profile.id)
        merged["client_profile_key"] = str(client_profile.profile_key or "").strip()
        return merged

    async def build_runtime_config(
        self,
        *,
        config: dict[str, Any] | SimpleNamespace,
        client_profile: MessagingClientProfileDE,
    ) -> SimpleNamespace:
        root = self._plain_data(config)
        if not isinstance(root, dict):
            raise TypeError("Configuration root must be a mapping.")
        cloned = copy.deepcopy(root)
        cloned[str(client_profile.platform_key)] = (
            await self.build_runtime_platform_section(
                config=config,
                client_profile=client_profile,
            )
        )
        return build_config_namespace(cloned)

    async def list_active_runtime_specs(
        self,
        *,
        config: dict[str, Any] | SimpleNamespace,
        platform_key: str,
    ) -> tuple[RuntimeMessagingClientProfileSpec, ...]:
        normalized_platform_key = self._normalize_platform_key(platform_key)
        client_profiles = await self.list(
            filter_groups=[
                FilterGroup(
                    where={
                        "platform_key": normalized_platform_key,
                        "is_active": True,
                    }
                )
            ],
            order_by=[
                OrderBy("tenant_id", descending=False),
                OrderBy("profile_key", descending=False),
                OrderBy("id", descending=False),
            ],
        )

        specs: list[RuntimeMessagingClientProfileSpec] = []
        for client_profile in client_profiles:
            if client_profile.id is None or client_profile.tenant_id is None:
                continue
            specs.append(
                RuntimeMessagingClientProfileSpec(
                    client_profile_id=client_profile.id,
                    tenant_id=client_profile.tenant_id,
                    platform_key=normalized_platform_key,
                    profile_key=str(client_profile.profile_key or "").strip(),
                    config=await self.build_runtime_config(
                        config=config,
                        client_profile=client_profile,
                    ),
                    snapshot=self._snapshot_for_runtime(client_profile),
                )
            )
        return tuple(specs)

    async def resolve_active_by_id(
        self,
        *,
        client_profile_id: uuid.UUID | str,
    ) -> MessagingClientProfileDE | None:
        normalized_client_profile_id = uuid.UUID(str(client_profile_id).strip())
        return await self.get(
            {
                "id": normalized_client_profile_id,
                "is_active": True,
            }
        )

    async def resolve_active_by_identifier(
        self,
        *,
        platform_key: str,
        identifier_type: str,
        identifier_value: str | None,
        filters: dict[str, str] | None = None,
    ) -> MessagingClientProfileDE | None:
        normalized_platform_key = self._normalize_platform_key(platform_key)
        normalized_identifier_type = self._normalize_required_text(
            identifier_type,
            field_name="IdentifierType",
        )
        normalized_identifier_value = self._normalize_optional_text(identifier_value)
        if normalized_identifier_value is None:
            return None

        column_name = _IDENTIFIER_COLUMNS.get(normalized_identifier_type)
        if column_name is None:
            return None

        where = {
            "platform_key": normalized_platform_key,
            "is_active": True,
            column_name: normalized_identifier_value,
        }
        for raw_key, raw_value in (filters or {}).items():
            filter_key = self._normalize_optional_text(raw_key)
            filter_value = self._normalize_optional_text(raw_value)
            if filter_key is None or filter_value is None:
                continue
            filter_column = _IDENTIFIER_COLUMNS.get(filter_key)
            if filter_column is None:
                continue
            where[filter_column] = filter_value

        rows = await self.list(
            filter_groups=[FilterGroup(where=where)],
            limit=2,
        )
        if len(rows) != 1:
            return None
        return rows[0]

    async def create(self, values: dict[str, Any]) -> MessagingClientProfileDE:
        payload = dict(values)
        payload["tenant_id"] = self._normalize_tenant_id(payload.get("tenant_id"))
        payload["platform_key"] = self._normalize_platform_key(
            payload.get("platform_key")
        )
        payload["profile_key"] = self._normalize_required_text(
            payload.get("profile_key"),
            field_name="ProfileKey",
        )
        payload["display_name"] = self._normalize_optional_text(
            payload.get("display_name")
        )
        payload["settings"] = self._normalize_mapping(payload.get("settings"))
        payload["secret_refs"] = self._normalize_secret_refs(payload.get("secret_refs"))
        self._normalize_identifier_fields(
            payload=payload,
            platform_key=payload["platform_key"],
        )
        await self._validate_secret_refs(
            tenant_id=payload["tenant_id"],
            secret_refs=payload["secret_refs"],
        )
        created = await super().create(payload)
        await self._reload_runtime_profiles_for_platforms(payload["platform_key"])
        return created

    async def update(
        self,
        where: dict[str, Any],
        changes: dict[str, Any],
    ) -> MessagingClientProfileDE | None:
        current = await self.get(where)
        if current is None:
            return None

        payload = {
            "tenant_id": self._normalize_tenant_id(
                changes.get("tenant_id", current.tenant_id)
            ),
            "platform_key": self._normalize_platform_key(
                changes.get("platform_key", current.platform_key)
            ),
            "profile_key": self._normalize_required_text(
                changes.get("profile_key", current.profile_key),
                field_name="ProfileKey",
            ),
            "display_name": self._normalize_optional_text(
                changes.get("display_name", current.display_name)
            ),
            "settings": self._normalize_mapping(
                changes.get("settings", current.settings or {})
            ),
            "secret_refs": self._normalize_secret_refs(
                changes.get("secret_refs", current.secret_refs or {})
            ),
            "is_active": bool(changes.get("is_active", current.is_active)),
            "path_token": changes.get("path_token", current.path_token),
            "recipient_user_id": changes.get(
                "recipient_user_id",
                current.recipient_user_id,
            ),
            "account_number": changes.get("account_number", current.account_number),
            "phone_number_id": changes.get(
                "phone_number_id",
                current.phone_number_id,
            ),
            "provider": changes.get("provider", current.provider),
        }
        self._normalize_identifier_fields(
            payload=payload,
            platform_key=payload["platform_key"],
        )
        await self._validate_secret_refs(
            tenant_id=payload["tenant_id"],
            secret_refs=payload["secret_refs"],
        )
        updated = await super().update(where, payload)
        if updated is not None:
            await self._reload_runtime_profiles_for_platforms(
                current.platform_key,
                payload["platform_key"],
            )
        return updated

    async def update_with_row_version(
        self,
        where: dict[str, Any],
        *,
        expected_row_version: int,
        changes: dict[str, Any],
    ) -> MessagingClientProfileDE | None:
        current = await self.get(where)
        if current is None:
            return None

        payload = {
            "tenant_id": self._normalize_tenant_id(
                changes.get("tenant_id", current.tenant_id)
            ),
            "platform_key": self._normalize_platform_key(
                changes.get("platform_key", current.platform_key)
            ),
            "profile_key": self._normalize_required_text(
                changes.get("profile_key", current.profile_key),
                field_name="ProfileKey",
            ),
            "display_name": self._normalize_optional_text(
                changes.get("display_name", current.display_name)
            ),
            "settings": self._normalize_mapping(
                changes.get("settings", current.settings or {})
            ),
            "secret_refs": self._normalize_secret_refs(
                changes.get("secret_refs", current.secret_refs or {})
            ),
            "is_active": bool(changes.get("is_active", current.is_active)),
            "path_token": changes.get("path_token", current.path_token),
            "recipient_user_id": changes.get(
                "recipient_user_id",
                current.recipient_user_id,
            ),
            "account_number": changes.get("account_number", current.account_number),
            "phone_number_id": changes.get(
                "phone_number_id",
                current.phone_number_id,
            ),
            "provider": changes.get("provider", current.provider),
        }
        self._normalize_identifier_fields(
            payload=payload,
            platform_key=payload["platform_key"],
        )
        await self._validate_secret_refs(
            tenant_id=payload["tenant_id"],
            secret_refs=payload["secret_refs"],
        )
        updated = await super().update_with_row_version(
            where,
            expected_row_version=expected_row_version,
            changes=payload,
        )
        if updated is not None:
            await self._reload_runtime_profiles_for_platforms(
                current.platform_key,
                payload["platform_key"],
            )
        return updated

    async def delete(self, where: dict[str, Any]) -> MessagingClientProfileDE | None:
        current = await self.get(where)
        if current is None:
            return None
        deleted = await super().delete(where)
        if deleted is not None:
            await self._reload_runtime_profiles_for_platforms(current.platform_key)
        return deleted

    async def delete_with_row_version(
        self,
        where: dict[str, Any],
        *,
        expected_row_version: int,
    ) -> MessagingClientProfileDE | None:
        current = await self.get(where)
        if current is None:
            return None
        deleted = await super().delete_with_row_version(
            where,
            expected_row_version=expected_row_version,
        )
        if deleted is not None:
            await self._reload_runtime_profiles_for_platforms(current.platform_key)
        return deleted

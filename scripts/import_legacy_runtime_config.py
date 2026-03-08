#!/usr/bin/env python3
"""Import legacy runtime config into ACP-managed messaging and secret rows."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any
import tomllib

import sqlalchemy as sa
from sqlalchemy import MetaData, Table
from sqlalchemy.dialects.postgresql import insert as pg_insert

from mugen.core.plugin.acp.constants import GLOBAL_TENANT_ID
from mugen.core.plugin.acp.service.key_provider import (
    LocalConfigKeyMaterialProvider,
    ManagedKeyMaterialCipher,
)
from mugen.core.plugin.acp.utility.runtime_config_policy import (
    normalize_tenant_messaging_settings,
    normalize_messaging_platform_key,
)
from mugen.core.utility.platform_runtime_profile import build_config_namespace

_DEFAULT_CONFIG_PATH = "mugen.toml"
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SUPPORTED_PLATFORMS = (
    "line",
    "matrix",
    "signal",
    "telegram",
    "wechat",
    "whatsapp",
)


@dataclass(frozen=True, slots=True)
class LocalKeyMaterial:
    """Resolved local-provider key material imported into one managed row."""

    purpose: str
    key_id: str
    secret_value: str


@dataclass(frozen=True, slots=True)
class LegacyMessagingProfile:
    """Legacy profile payload normalized for ACP import."""

    platform_key: str
    profile_key: str
    display_name: str | None
    settings: dict[str, Any]
    secret_values: dict[str, str]
    path_token: str | None = None
    recipient_user_id: str | None = None
    account_number: str | None = None
    phone_number_id: str | None = None
    provider: str | None = None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import legacy config-backed runtime secrets and messaging profiles "
            "into ACP-managed rows."
        )
    )
    parser.add_argument(
        "--config",
        default=_DEFAULT_CONFIG_PATH,
        help=f"Path to mugen TOML config (default: {_DEFAULT_CONFIG_PATH}).",
    )
    parser.add_argument(
        "--schema",
        default="mugen",
        help="Target DB schema for ACP tables (default: mugen).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print import plan without applying DB changes.",
    )
    return parser.parse_args()


def _load_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    if isinstance(payload, dict) is not True:
        raise RuntimeError(f"Config file must parse to a TOML table: {path}")
    return payload


def _validate_identifier(name: str, label: str) -> str:
    if not _IDENT_RE.fullmatch(name):
        raise ValueError(f"Invalid {label}: {name!r}")
    return name


def _resolve_rdbms_url(config: dict[str, Any]) -> str:
    for candidate in [
        config.get("rdbms", {}).get("sqlalchemy", {}).get("url"),
        config.get("rdbms", {}).get("alembic", {}).get("url"),
    ]:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    raise RuntimeError(
        "Could not resolve relational URL from rdbms.sqlalchemy.url or "
        "rdbms.alembic.url."
    )


def _normalize_optional_text(value: object) -> str | None:
    if isinstance(value, str) is not True:
        return None
    normalized = value.strip()
    return normalized or None


def _require_text(value: object, *, field_name: str) -> str:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        raise RuntimeError(f"{field_name} must be non-empty.")
    return normalized


def _mapping(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _nested(value: dict[str, Any], *path: str) -> Any:
    current: Any = value
    for part in path:
        if isinstance(current, dict) is not True:
            return None
        current = current.get(part)
    return current


def _set_nested(payload: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current = payload
    for part in path[:-1]:
        node = current.get(part)
        if isinstance(node, dict) is not True:
            node = {}
            current[part] = node
        current = node
    current[path[-1]] = value


def _resolved_secret(value: object) -> str | None:
    return LocalConfigKeyMaterialProvider._resolve_secret(value)


def _iter_local_key_material(config: dict[str, Any]) -> tuple[list[LocalKeyMaterial], list[str]]:
    key_map = (
        config.get("acp", {})
        .get("key_management", {})
        .get("providers", {})
        .get("local", {})
        .get("keys", {})
    )
    purpose_entries: list[LocalKeyMaterial] = []
    fallback_key_ids: list[str] = []

    for raw_purpose, raw_value in _mapping(key_map).items():
        purpose = _normalize_optional_text(raw_purpose)
        if purpose is None:
            continue
        if isinstance(raw_value, dict):
            if set(raw_value).issubset({"env", "value"}):
                fallback_key_ids.append(purpose)
                continue
            for raw_key_id, raw_secret in raw_value.items():
                key_id = _normalize_optional_text(raw_key_id)
                secret_value = _resolved_secret(raw_secret)
                if key_id is None or secret_value is None:
                    continue
                purpose_entries.append(
                    LocalKeyMaterial(
                        purpose=purpose,
                        key_id=key_id,
                        secret_value=secret_value,
                    )
                )
            continue

        secret_value = _resolved_secret(raw_value)
        if secret_value is not None:
            fallback_key_ids.append(purpose)

    return purpose_entries, fallback_key_ids


def _legacy_managed_key_ref_identity(
    *,
    platform_key: str,
    profile_key: str,
    dotted_path: str,
) -> tuple[str, str]:
    purpose = "messaging_client_secret"
    raw_key_id = ".".join(
        [
            "global",
            platform_key.strip().lower(),
            profile_key.strip().lower(),
            dotted_path.strip().lower().replace(".", "_"),
        ]
    )
    if len(raw_key_id) <= 128:
        return purpose, raw_key_id

    digest = hashlib.sha256(raw_key_id.encode("utf-8")).hexdigest()[:16]
    shortened = raw_key_id[:110].rstrip(".-_")
    return purpose, f"{shortened}.{digest}"


def _extract_legacy_profile(
    *,
    platform_key: str,
    payload: dict[str, Any],
) -> LegacyMessagingProfile:
    profile_key = _require_text(payload.get("key"), field_name="profiles[].key")
    platform = normalize_messaging_platform_key(platform_key)
    settings: dict[str, Any] = {}
    secret_values: dict[str, str] = {}
    display_name: str | None = None
    path_token = None
    recipient_user_id = None
    account_number = None
    phone_number_id = None
    provider = None

    if platform == "line":
        for dotted_path in ("channel.access_token", "channel.secret"):
            secret_value = _resolved_secret(
                _nested(payload, *dotted_path.split("."))
            )
            if secret_value is not None:
                secret_values[dotted_path] = secret_value
        path_token = _normalize_optional_text(_nested(payload, "webhook", "path_token"))
    elif platform == "matrix":
        for dotted_path in ("homeserver", "client.device", "room_id"):
            value = _nested(payload, *dotted_path.split("."))
            if value is not None:
                _set_nested(settings, tuple(dotted_path.split(".")), value)
        secret_value = _resolved_secret(_nested(payload, "client", "password"))
        if secret_value is not None:
            secret_values["client.password"] = secret_value
        recipient_user_id = _normalize_optional_text(
            _nested(payload, "client", "user")
        )
        display_name = (
            _normalize_optional_text(payload.get("profile_displayname"))
            or _normalize_optional_text(_nested(payload, "assistant", "name"))
        )
    elif platform == "signal":
        value = _nested(payload, "api", "base_url")
        if value is not None:
            _set_nested(settings, ("api", "base_url"), value)
        secret_value = _resolved_secret(_nested(payload, "api", "bearer_token"))
        if secret_value is not None:
            secret_values["api.bearer_token"] = secret_value
        account_number = _normalize_optional_text(_nested(payload, "account", "number"))
    elif platform == "telegram":
        for dotted_path in ("bot.token", "webhook.secret_token"):
            secret_value = _resolved_secret(
                _nested(payload, *dotted_path.split("."))
            )
            if secret_value is not None:
                secret_values[dotted_path] = secret_value
        path_token = _normalize_optional_text(_nested(payload, "webhook", "path_token"))
    elif platform == "wechat":
        for dotted_path in (
            "webhook.aes_enabled",
            "official_account.app_id",
            "wecom.corp_id",
            "wecom.agent_id",
        ):
            value = _nested(payload, *dotted_path.split("."))
            if value is not None:
                _set_nested(settings, tuple(dotted_path.split(".")), value)
        for dotted_path in (
            "webhook.signature_token",
            "webhook.aes_key",
            "official_account.app_secret",
            "wecom.corp_secret",
        ):
            secret_value = _resolved_secret(
                _nested(payload, *dotted_path.split("."))
            )
            if secret_value is not None:
                secret_values[dotted_path] = secret_value
        path_token = _normalize_optional_text(_nested(payload, "webhook", "path_token"))
        provider = _normalize_optional_text(payload.get("provider"))
    else:
        value = _nested(payload, "app", "id")
        if value is not None:
            _set_nested(settings, ("app", "id"), value)
        for dotted_path in (
            "app.secret",
            "graphapi.access_token",
            "webhook.verification_token",
        ):
            secret_value = _resolved_secret(
                _nested(payload, *dotted_path.split("."))
            )
            if secret_value is not None:
                secret_values[dotted_path] = secret_value
        path_token = _normalize_optional_text(_nested(payload, "webhook", "path_token"))
        phone_number_id = _normalize_optional_text(
            _nested(payload, "business", "phone_number_id")
        )

    return LegacyMessagingProfile(
        platform_key=platform,
        profile_key=profile_key,
        display_name=display_name,
        settings=normalize_tenant_messaging_settings(
            platform_key=platform,
            value=settings,
        ),
        secret_values=secret_values,
        path_token=path_token,
        recipient_user_id=recipient_user_id,
        account_number=account_number,
        phone_number_id=phone_number_id,
        provider=provider,
    )


def _extract_legacy_messaging_profiles(
    config: dict[str, Any],
) -> list[LegacyMessagingProfile]:
    profiles: list[LegacyMessagingProfile] = []
    for platform_key in _SUPPORTED_PLATFORMS:
        platform_cfg = _mapping(config.get(platform_key))
        raw_profiles = platform_cfg.get("profiles")
        if isinstance(raw_profiles, list) is not True:
            continue
        for raw_profile in raw_profiles:
            if isinstance(raw_profile, dict) is not True:
                continue
            profiles.append(
                _extract_legacy_profile(
                    platform_key=platform_key,
                    payload=raw_profile,
                )
            )
    return profiles


def _ops_connector_defaults(config: dict[str, Any]) -> dict[str, Any]:
    cfg = _mapping(config.get("ops_connector"))
    settings: dict[str, Any] = {}
    for key in (
        "timeout_seconds_default",
        "max_retries_default",
        "retry_backoff_seconds_default",
        "retry_status_codes_default",
        "redacted_keys",
    ):
        if key in cfg:
            settings[key] = cfg[key]
    return settings


def _reflect_table(engine, *, schema: str, table_name: str) -> Table:
    metadata = MetaData(schema=schema)
    return Table(table_name, metadata, autoload_with=engine)


def _upsert_managed_key_ref(
    conn,
    *,
    key_ref_table: Table,
    tenant_id,
    purpose: str,
    key_id: str,
    encrypted_secret: str,
    attributes: dict[str, Any] | None,
):
    existing = conn.execute(
        sa.select(key_ref_table.c.id, key_ref_table.c.status).where(
            key_ref_table.c.tenant_id == tenant_id,
            key_ref_table.c.purpose == purpose,
            key_ref_table.c.key_id == key_id,
        )
    ).first()
    if existing is not None and str(existing.status or "").strip().lower() == "destroyed":
        raise RuntimeError(
            "Cannot import managed material into destroyed KeyRef "
            f"({purpose!r}, {key_id!r})."
        )

    stmt = pg_insert(key_ref_table).values(
        tenant_id=tenant_id,
        purpose=purpose,
        key_id=key_id,
        provider="managed",
        status="active",
        activated_at=sa.func.now(),
        retired_at=None,
        retired_by_user_id=None,
        retired_reason=None,
        destroyed_at=None,
        destroyed_by_user_id=None,
        destroy_reason=None,
        encrypted_secret=encrypted_secret,
        has_material=True,
        material_last_set_at=sa.func.now(),
        material_last_set_by_user_id=None,
        attributes=attributes,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            key_ref_table.c.tenant_id,
            key_ref_table.c.purpose,
            key_ref_table.c.key_id,
        ],
        set_={
            "provider": "managed",
            "status": "active",
            "activated_at": sa.func.now(),
            "retired_at": None,
            "retired_by_user_id": None,
            "retired_reason": None,
            "destroyed_at": None,
            "destroyed_by_user_id": None,
            "destroy_reason": None,
            "encrypted_secret": encrypted_secret,
            "has_material": True,
            "material_last_set_at": sa.func.now(),
            "attributes": attributes,
        },
    ).returning(key_ref_table.c.id)
    return conn.execute(stmt).scalar_one()


def _upsert_messaging_client_profile(
    conn,
    *,
    client_profile_table: Table,
    profile: LegacyMessagingProfile,
    secret_refs: dict[str, str],
):
    stmt = pg_insert(client_profile_table).values(
        tenant_id=GLOBAL_TENANT_ID,
        platform_key=profile.platform_key,
        profile_key=profile.profile_key,
        display_name=profile.display_name,
        is_active=True,
        settings=profile.settings,
        secret_refs=secret_refs,
        path_token=profile.path_token,
        recipient_user_id=profile.recipient_user_id,
        account_number=profile.account_number,
        phone_number_id=profile.phone_number_id,
        provider=profile.provider,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            client_profile_table.c.tenant_id,
            client_profile_table.c.platform_key,
            client_profile_table.c.profile_key,
        ],
        set_={
            "display_name": profile.display_name,
            "is_active": True,
            "settings": profile.settings,
            "secret_refs": secret_refs,
            "path_token": profile.path_token,
            "recipient_user_id": profile.recipient_user_id,
            "account_number": profile.account_number,
            "phone_number_id": profile.phone_number_id,
            "provider": profile.provider,
        },
    ).returning(client_profile_table.c.id)
    return conn.execute(stmt).scalar_one()


def _upsert_runtime_config_profile(
    conn,
    *,
    runtime_config_table: Table,
    settings_json: dict[str, Any],
):
    stmt = pg_insert(runtime_config_table).values(
        tenant_id=GLOBAL_TENANT_ID,
        category="ops_connector.defaults",
        profile_key="default",
        display_name="Imported Ops Connector Defaults",
        is_active=True,
        settings_json=settings_json,
        attributes={"import_source": "legacy_runtime_config"},
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            runtime_config_table.c.tenant_id,
            runtime_config_table.c.category,
            runtime_config_table.c.profile_key,
        ],
        set_={
            "display_name": "Imported Ops Connector Defaults",
            "is_active": True,
            "settings_json": settings_json,
            "attributes": {"import_source": "legacy_runtime_config"},
        },
    ).returning(runtime_config_table.c.id)
    return conn.execute(stmt).scalar_one()


def import_runtime_config(
    *,
    config_path: Path,
    schema: str,
    dry_run: bool,
) -> int:
    config = _load_config(config_path)
    runtime_ns = build_config_namespace(config)
    cipher = ManagedKeyMaterialCipher(config_provider=lambda: runtime_ns)

    local_key_material, fallback_key_ids = _iter_local_key_material(config)
    legacy_profiles = _extract_legacy_messaging_profiles(config)
    ops_connector_defaults = _ops_connector_defaults(config)

    if dry_run:
        print("DRY_RUN: no DB changes applied")
        print(f"local_key_material={len(local_key_material)}")
        print(f"local_fallback_key_ids={len(fallback_key_ids)}")
        print(f"legacy_messaging_profiles={len(legacy_profiles)}")
        print(f"ops_connector_defaults_keys={len(ops_connector_defaults)}")
        return 0

    engine = sa.create_engine(_resolve_rdbms_url(config))
    key_ref_table = _reflect_table(engine, schema=schema, table_name="admin_key_ref")
    client_profile_table = _reflect_table(
        engine,
        schema=schema,
        table_name="admin_messaging_client_profile",
    )
    runtime_config_table = _reflect_table(
        engine,
        schema=schema,
        table_name="admin_runtime_config_profile",
    )

    imported_key_refs = 0
    imported_profiles = 0
    fallback_updates = 0

    with engine.begin() as conn:
        for entry in local_key_material:
            _upsert_managed_key_ref(
                conn,
                key_ref_table=key_ref_table,
                tenant_id=GLOBAL_TENANT_ID,
                purpose=entry.purpose,
                key_id=entry.key_id,
                encrypted_secret=cipher.encrypt(entry.secret_value),
                attributes={"import_source": "legacy_local_key_map"},
            )
            imported_key_refs += 1

        for key_id in fallback_key_ids:
            existing_rows = conn.execute(
                sa.select(key_ref_table.c.purpose).where(
                    key_ref_table.c.tenant_id == GLOBAL_TENANT_ID,
                    key_ref_table.c.key_id == key_id,
                )
            ).all()
            for row in existing_rows:
                raw_secret = (
                    config.get("acp", {})
                    .get("key_management", {})
                    .get("providers", {})
                    .get("local", {})
                    .get("keys", {})
                    .get(key_id)
                )
                secret_value = _resolved_secret(raw_secret)
                if secret_value is None:
                    continue
                _upsert_managed_key_ref(
                    conn,
                    key_ref_table=key_ref_table,
                    tenant_id=GLOBAL_TENANT_ID,
                    purpose=str(row.purpose),
                    key_id=key_id,
                    encrypted_secret=cipher.encrypt(secret_value),
                    attributes={"import_source": "legacy_local_key_fallback"},
                )
                fallback_updates += 1

        for profile in legacy_profiles:
            secret_refs: dict[str, str] = {}
            for dotted_path, secret_value in profile.secret_values.items():
                purpose, key_id = _legacy_managed_key_ref_identity(
                    platform_key=profile.platform_key,
                    profile_key=profile.profile_key,
                    dotted_path=dotted_path,
                )
                key_ref_id = _upsert_managed_key_ref(
                    conn,
                    key_ref_table=key_ref_table,
                    tenant_id=GLOBAL_TENANT_ID,
                    purpose=purpose,
                    key_id=key_id,
                    encrypted_secret=cipher.encrypt(secret_value),
                    attributes={
                        "import_source": "legacy_messaging_profile",
                        "platform_key": profile.platform_key,
                        "profile_key": profile.profile_key,
                        "secret_path": dotted_path,
                    },
                )
                secret_refs[dotted_path] = str(key_ref_id)
                imported_key_refs += 1

            _upsert_messaging_client_profile(
                conn,
                client_profile_table=client_profile_table,
                profile=profile,
                secret_refs=secret_refs,
            )
            imported_profiles += 1

        _upsert_runtime_config_profile(
            conn,
            runtime_config_table=runtime_config_table,
            settings_json=ops_connector_defaults,
        )

    print("IMPORT_APPLIED")
    print(f"imported_key_refs={imported_key_refs}")
    print(f"fallback_key_ref_updates={fallback_updates}")
    print(f"imported_messaging_profiles={imported_profiles}")
    print("cleanup_next_steps:")
    print("1. Verify imported KeyRefs and MessagingClientProfiles in ACP.")
    print("2. Remove legacy [[<platform>.profiles]] blocks from local config after verification.")
    print("3. Remove operator-local key maps under acp.key_management.providers.local.keys once no ACP rows depend on provider='local'.")
    print("4. Review duplicated ops_connector defaults and keep only the desired bootstrap fallback in root config.")
    return 0


def main() -> int:
    args = _parse_args()
    config_path = Path(args.config)
    if config_path.exists() is not True:
        raise FileNotFoundError(f"Config file not found: {config_path}")

    return import_runtime_config(
        config_path=config_path,
        schema=_validate_identifier(args.schema, "schema name"),
        dry_run=bool(args.dry_run),
    )


if __name__ == "__main__":
    raise SystemExit(main())

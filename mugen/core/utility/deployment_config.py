"""Deployment environment overlay and validation helpers."""

from __future__ import annotations

__all__ = [
    "apply_environment_overrides",
    "parse_log_level",
    "validate_production_deployment_config",
]

from collections.abc import Mapping
from copy import deepcopy
import json
import logging
import os
from pathlib import Path
import tomllib
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from werkzeug.security import check_password_hash, generate_password_hash

from mugen.core.utility.security import (
    validate_acp_managed_secret_encryption_key,
    validate_quart_secret_key,
)

_STRING_PATH_OVERRIDES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ENVIRONMENT", ("mugen", "environment")),
    ("APP_NAME", ("mugen", "logger", "name")),
    ("DATABASE_URL", ("rdbms", "alembic", "url")),
    ("DATABASE_URL", ("rdbms", "sqlalchemy", "url")),
    ("SECRET_KEY", ("quart", "secret_key")),
    ("ACP_SECRET_KEY", ("acp", "secret_key")),
    ("ACP_ADMIN_USERNAME", ("acp", "admin_username")),
    ("ACP_ADMIN_LOGIN_EMAIL", ("acp", "admin_login_email")),
    ("ACP_ADMIN_PASSWORD", ("acp", "admin_password")),
    ("ACP_ADMIN_PASSWORD_HASH", ("acp", "admin_password_hash")),
    (
        "ACP_MANAGED_SECRET_ENCRYPTION_KEY",
        ("acp", "key_management", "providers", "managed", "encryption_key"),
    ),
    ("ACP_REFRESH_TOKEN_PEPPER", ("acp", "refresh_token_pepper")),
)
_BOOL_PATH_OVERRIDES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ACP_SEED_ACP", ("acp", "seed_acp")),
)
_JWT_STRING_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("ACP_JWT_ACTIVE_KID", "active_kid"),
    ("ACP_JWT_ISSUER", "issuer"),
    ("ACP_JWT_AUDIENCE", "audience"),
)
_CONFIG_OVERLAY_FILE_ENV = "MUGEN_CONFIG_OVERLAY_FILE"
_CONFIG_OVERLAY_JSON_ENV = "MUGEN_CONFIG_OVERLAY_JSON"
_BUILTIN_EXTENSION_PRESETS: dict[str, dict[str, Any]] = {
    "core.fw.audit": {
        "type": "fw",
        "token": "core.fw.audit",
        "enabled": True,
        "name": "com.vorsocomputing.mugen.audit",
        "namespace": "com.vorsocomputing.mugen.audit",
        "models": "mugen.core.plugin.audit.model",
        "migration_track": "core",
        "contrib": "mugen.core.plugin.audit.contrib",
    },
    "core.fw.channel_orchestration": {
        "type": "fw",
        "token": "core.fw.channel_orchestration",
        "enabled": True,
        "name": "com.vorsocomputing.mugen.channel_orchestration",
        "namespace": "com.vorsocomputing.mugen.channel_orchestration",
        "models": "mugen.core.plugin.channel_orchestration.model",
        "migration_track": "core",
        "contrib": "mugen.core.plugin.channel_orchestration.contrib",
    },
}

_PLACEHOLDER_MARKERS = (
    "<set-",
    "<replace-",
    "<replace-with",
    "change-me",
    "changeme",
    "placeholder",
    "replace-me",
    "replace_me",
    "set-me",
    "set_me",
)


def _env_text(environ: Mapping[str, str], key: str) -> str | None:
    value = environ.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized != "" else None


def _set_path(config: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    node = config
    for key in path[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[path[-1]] = value


def _get_path(config: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = config
    for key in path:
        if not isinstance(node, Mapping):
            return None
        node = node.get(key)
    return node


def _ensure_jwt_config(config: dict[str, Any]) -> dict[str, Any]:
    acp = config.setdefault("acp", {})
    if not isinstance(acp, dict):
        acp = {}
        config["acp"] = acp

    jwt = acp.setdefault("jwt", {})
    if not isinstance(jwt, dict):
        jwt = {}
        acp["jwt"] = jwt
    return jwt


def _ensure_first_jwt_key(config: dict[str, Any]) -> dict[str, Any]:
    jwt = _ensure_jwt_config(config)
    keys = jwt.get("keys")
    if not isinstance(keys, list):
        keys = []
        jwt["keys"] = keys
    if not keys:
        keys.append({})
    if not isinstance(keys[0], dict):
        keys[0] = {}
    return keys[0]


def _parse_json_env(value: str, *, field_name: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Invalid configuration: {field_name} must be valid JSON."
        ) from exc


def _deep_merge_config(
    target: dict[str, Any],
    overlay: Mapping[str, Any],
) -> None:
    for key, overlay_value in overlay.items():
        existing_value = target.get(key)
        if isinstance(existing_value, dict) and isinstance(overlay_value, Mapping):
            _deep_merge_config(existing_value, overlay_value)
            continue
        target[key] = deepcopy(overlay_value)


def _require_overlay_object(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeError(
            f"Invalid configuration: {field_name} must be a JSON/TOML object."
        )
    return dict(value)


def _load_overlay_file(path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    if not path.exists():
        raise RuntimeError(
            "Invalid configuration: "
            f"{_CONFIG_OVERLAY_FILE_ENV} does not exist: {path_value}."
        )
    if not path.is_file():
        raise RuntimeError(
            "Invalid configuration: "
            f"{_CONFIG_OVERLAY_FILE_ENV} must point to a file: {path_value}."
        )

    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Invalid configuration: "
                f"{_CONFIG_OVERLAY_FILE_ENV} must contain valid JSON."
            ) from exc
        return _require_overlay_object(
            payload,
            field_name=_CONFIG_OVERLAY_FILE_ENV,
        )

    if suffix == ".toml":
        try:
            with path.open("rb") as file_obj:
                payload = tomllib.load(file_obj)
        except tomllib.TOMLDecodeError as exc:
            raise RuntimeError(
                "Invalid configuration: "
                f"{_CONFIG_OVERLAY_FILE_ENV} must contain valid TOML."
            ) from exc
        return _require_overlay_object(
            payload,
            field_name=_CONFIG_OVERLAY_FILE_ENV,
        )

    raise RuntimeError(
        "Invalid configuration: "
        f"{_CONFIG_OVERLAY_FILE_ENV} must use a .json or .toml file."
    )


def _apply_generic_config_overlays(
    config: dict[str, Any],
    env: Mapping[str, str],
) -> None:
    overlay_file = _env_text(env, _CONFIG_OVERLAY_FILE_ENV)
    if overlay_file is not None:
        _deep_merge_config(config, _load_overlay_file(overlay_file))

    overlay_json = _env_text(env, _CONFIG_OVERLAY_JSON_ENV)
    if overlay_json is not None:
        payload = _parse_json_env(overlay_json, field_name=_CONFIG_OVERLAY_JSON_ENV)
        _deep_merge_config(
            config,
            _require_overlay_object(payload, field_name=_CONFIG_OVERLAY_JSON_ENV),
        )


def _normalize_jwt_keys(value: Any, *, field_name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise RuntimeError(f"Invalid configuration: {field_name} must be a JSON array.")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise RuntimeError(
                "Invalid configuration: "
                f"{field_name}[{index}] must be a JSON object."
            )
        key = dict(item)
        pem = key.get("pem")
        if isinstance(pem, str):
            key["pem"] = pem.replace("\\n", "\n")
        normalized.append(key)
    return normalized


def _normalize_json_object_array(
    value: Any, *, field_name: str
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise RuntimeError(f"Invalid configuration: {field_name} must be a JSON array.")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise RuntimeError(
                "Invalid configuration: "
                f"{field_name}[{index}] must be a JSON object."
            )
        normalized.append(dict(item))
    return normalized


def parse_log_level(value: object, *, field_name: str = "LOG_LEVEL") -> int:
    """Parse numeric or named Python logging levels."""
    if isinstance(value, bool):
        raise RuntimeError(f"Invalid configuration: {field_name} is invalid.")
    if isinstance(value, int):
        if value < 0:
            raise RuntimeError(f"Invalid configuration: {field_name} is invalid.")
        return value
    if not isinstance(value, str):
        raise RuntimeError(f"Invalid configuration: {field_name} is invalid.")

    normalized = value.strip()
    if normalized == "":
        raise RuntimeError(f"Invalid configuration: {field_name} is invalid.")
    try:
        parsed = int(normalized)
    except ValueError:
        level = getattr(logging, normalized.upper(), None)
        if not isinstance(level, int):
            raise RuntimeError(f"Invalid configuration: {field_name} is invalid.")
        return level
    if parsed < 0:
        raise RuntimeError(f"Invalid configuration: {field_name} is invalid.")
    return parsed


def _parse_csv(value: str) -> list[str]:
    items: list[str] = []
    for item in value.split(","):
        normalized = item.strip()
        if normalized == "" or normalized in items:
            continue
        items.append(normalized)
    return items


def _apply_platform_overrides(
    config: dict[str, Any],
    env: Mapping[str, str],
) -> None:
    platforms_value = _env_text(env, "MUGEN_PLATFORMS")
    critical_platforms_value = _env_text(env, "MUGEN_PHASE_B_CRITICAL_PLATFORMS")

    platforms = _parse_csv(platforms_value) if platforms_value is not None else None
    critical_platforms = (
        _parse_csv(critical_platforms_value)
        if critical_platforms_value is not None
        else None
    )

    if platforms is not None:
        _set_path(config, ("mugen", "platforms"), platforms)

    if critical_platforms is not None:
        _set_path(
            config,
            ("mugen", "runtime", "phase_b", "critical_platforms"),
            critical_platforms,
        )
        return

    if platforms is not None:
        _set_path(
            config,
            ("mugen", "runtime", "phase_b", "critical_platforms"),
            list(platforms),
        )


def _ensure_extension_list(config: dict[str, Any]) -> list[Any]:
    mugen = config.setdefault("mugen", {})
    if not isinstance(mugen, dict):
        mugen = {}
        config["mugen"] = mugen

    modules = mugen.setdefault("modules", {})
    if not isinstance(modules, dict):
        modules = {}
        mugen["modules"] = modules

    extensions = modules.get("extensions")
    if not isinstance(extensions, list):
        extensions = []
        modules["extensions"] = extensions
    return extensions


def _apply_extension_json_overrides(
    config: dict[str, Any],
    env: Mapping[str, str],
) -> None:
    raw_value = _env_text(env, "MUGEN_EXTENSIONS_JSON")
    if raw_value is None:
        return

    parsed = _parse_json_env(raw_value, field_name="MUGEN_EXTENSIONS_JSON")
    overlay_entries = _normalize_json_object_array(
        parsed,
        field_name="MUGEN_EXTENSIONS_JSON",
    )

    extensions = _ensure_extension_list(config)
    by_token: dict[str, dict[str, Any]] = {}
    for entry in extensions:
        if not isinstance(entry, dict):
            continue
        token = entry.get("token")
        if isinstance(token, str) and token.strip() != "":
            by_token[token.strip().lower()] = entry

    for index, overlay_entry in enumerate(overlay_entries):
        token = overlay_entry.get("token")
        if not isinstance(token, str) or token.strip() == "":
            raise RuntimeError(
                "Invalid configuration: "
                f"MUGEN_EXTENSIONS_JSON[{index}].token is required."
            )

        normalized_token = token.strip().lower()
        existing = by_token.get(normalized_token)
        if existing is None:
            extensions.append(overlay_entry)
            by_token[normalized_token] = overlay_entry
            continue
        existing.update(overlay_entry)


def _apply_enabled_extension_overrides(
    config: dict[str, Any],
    env: Mapping[str, str],
) -> None:
    raw_value = _env_text(env, "MUGEN_ENABLED_EXTENSIONS")
    if raw_value is None:
        return

    extensions = _ensure_extension_list(config)
    by_token: dict[str, dict[str, Any]] = {}
    for entry in extensions:
        if not isinstance(entry, dict):
            continue
        token = entry.get("token")
        if isinstance(token, str) and token.strip() != "":
            by_token[token.strip().lower()] = entry

    for token in _parse_csv(raw_value):
        normalized_token = token.lower()
        existing = by_token.get(normalized_token)
        if existing is not None:
            preset = _BUILTIN_EXTENSION_PRESETS.get(normalized_token, {})
            for key, value in preset.items():
                existing.setdefault(key, value)
            existing["enabled"] = True
            continue

        preset = _BUILTIN_EXTENSION_PRESETS.get(normalized_token)
        if preset is not None:
            extensions.append(dict(preset))
            continue

        raise RuntimeError(
            "Invalid configuration: "
            f"MUGEN_ENABLED_EXTENSIONS contains unknown extension {token!r}. "
            "Declare the extension in the base config or add a built-in preset."
        )


def _ensure_migration_plugin_tracks(config: dict[str, Any]) -> list[Any]:
    rdbms = config.setdefault("rdbms", {})
    if not isinstance(rdbms, dict):
        rdbms = {}
        config["rdbms"] = rdbms

    migration_tracks = rdbms.setdefault("migration_tracks", {})
    if not isinstance(migration_tracks, dict):
        migration_tracks = {}
        rdbms["migration_tracks"] = migration_tracks

    plugin_tracks = migration_tracks.get("plugins")
    if not isinstance(plugin_tracks, list):
        plugin_tracks = []
        migration_tracks["plugins"] = plugin_tracks
    return plugin_tracks


def _apply_migration_track_json_overrides(
    config: dict[str, Any],
    env: Mapping[str, str],
) -> None:
    raw_value = _env_text(env, "MUGEN_MIGRATION_TRACKS_JSON")
    if raw_value is None:
        return

    parsed = _parse_json_env(raw_value, field_name="MUGEN_MIGRATION_TRACKS_JSON")
    overlay_tracks = _normalize_json_object_array(
        parsed,
        field_name="MUGEN_MIGRATION_TRACKS_JSON",
    )

    plugin_tracks = _ensure_migration_plugin_tracks(config)
    by_name: dict[str, dict[str, Any]] = {}
    for entry in plugin_tracks:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if isinstance(name, str) and name.strip() != "":
            by_name[name.strip()] = entry

    for index, overlay_track in enumerate(overlay_tracks):
        name = overlay_track.get("name")
        if not isinstance(name, str) or name.strip() == "":
            raise RuntimeError(
                "Invalid configuration: "
                f"MUGEN_MIGRATION_TRACKS_JSON[{index}].name is required."
            )

        normalized_name = name.strip()
        existing = by_name.get(normalized_name)
        if existing is None:
            plugin_tracks.append(overlay_track)
            by_name[normalized_name] = overlay_track
            continue
        existing.update(overlay_track)


def _parse_bool(value: str, *, field_name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"Invalid configuration: {field_name} is invalid.")


def _is_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered.startswith("<") and lowered.endswith(">"):
        return True
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def _is_production_environment(config: Mapping[str, Any]) -> bool:
    environment = _get_path(config, ("mugen", "environment"))
    return isinstance(environment, str) and environment.strip().lower() == "production"


def _generate_ed25519_private_pem() -> str:
    private_key = ed25519.Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode("utf-8")


def _ensure_local_development_jwt_key(
    config: dict[str, Any],
    env: Mapping[str, str],
) -> None:
    if _is_production_environment(config):
        return
    if _env_text(env, "ACP_JWT_CONFIG_JSON") is not None:
        return
    if _env_text(env, "ACP_JWT_ACTIVE_KID") is None:
        return

    jwt_key = _ensure_first_jwt_key(config)
    current_pem = jwt_key.get("pem")
    if (
        not isinstance(current_pem, str)
        or current_pem.strip() == ""
        or _is_placeholder(current_pem)
    ):
        jwt_key["pem"] = _generate_ed25519_private_pem()


def _apply_jwt_overrides(
    config: dict[str, Any],
    env: Mapping[str, str],
) -> None:
    jwt_config_json = _env_text(env, "ACP_JWT_CONFIG_JSON")
    if jwt_config_json is not None:
        parsed = _parse_json_env(
            jwt_config_json,
            field_name="ACP_JWT_CONFIG_JSON",
        )
        if not isinstance(parsed, Mapping):
            raise RuntimeError(
                "Invalid configuration: ACP_JWT_CONFIG_JSON must be a JSON object."
            )

        jwt = _ensure_jwt_config(config)
        for key, value in parsed.items():
            if key == "keys":
                jwt["keys"] = _normalize_jwt_keys(
                    value,
                    field_name="ACP_JWT_CONFIG_JSON.keys",
                )
                continue
            jwt[str(key)] = value
        return

    for env_key, field_name in _JWT_STRING_OVERRIDES:
        value = _env_text(env, env_key)
        if value is None:
            continue
        _ensure_jwt_config(config)[field_name] = value

    jwt_active_kid = _env_text(env, "ACP_JWT_ACTIVE_KID")
    if jwt_active_kid is not None:
        jwt_key = _ensure_first_jwt_key(config)
        jwt_key["kid"] = jwt_active_kid
        jwt_key.setdefault("alg", "EdDSA")


def apply_environment_overrides(
    config: dict[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Apply deployment environment overrides to a loaded config mapping."""
    if not isinstance(config, dict):
        raise RuntimeError("Configuration payload must be a dict.")

    env = os.environ if environ is None else environ
    _apply_generic_config_overlays(config, env)
    _apply_platform_overrides(config, env)
    _apply_extension_json_overrides(config, env)
    _apply_enabled_extension_overrides(config, env)
    _apply_migration_track_json_overrides(config, env)

    for env_key, path in _STRING_PATH_OVERRIDES:
        value = _env_text(env, env_key)
        if value is None:
            continue
        _set_path(config, path, value)

    admin_password = _env_text(env, "ACP_ADMIN_PASSWORD")
    if admin_password is not None and _env_text(env, "ACP_ADMIN_PASSWORD_HASH") is None:
        current_hash = _get_path(config, ("acp", "admin_password_hash"))
        if not isinstance(current_hash, str) or current_hash.strip() == "":
            _set_path(
                config,
                ("acp", "admin_password_hash"),
                generate_password_hash(admin_password),
            )

    for env_key, path in _BOOL_PATH_OVERRIDES:
        value = _env_text(env, env_key)
        if value is None:
            continue
        _set_path(config, path, _parse_bool(value, field_name=env_key))

    log_level = _env_text(env, "LOG_LEVEL")
    if log_level is not None:
        _set_path(
            config,
            ("mugen", "logger", "level"),
            parse_log_level(log_level),
        )

    cors_origins = _env_text(env, "CORS_ALLOWED_ORIGINS")
    if cors_origins is not None:
        _set_path(config, ("acp", "cors_origins"), _parse_csv(cors_origins))

    _apply_jwt_overrides(config, env)
    _ensure_local_development_jwt_key(config, env)

    return config


def _require_string(config: Mapping[str, Any], path: tuple[str, ...]) -> str:
    value = _get_path(config, path)
    dotted = ".".join(path)
    if not isinstance(value, str) or value.strip() == "":
        raise RuntimeError(f"Invalid production configuration: {dotted} is required.")
    normalized = value.strip()
    if _is_placeholder(normalized):
        raise RuntimeError(
            f"Invalid production configuration: {dotted} must not be a placeholder."
        )
    return normalized


def _require_database_url(config: Mapping[str, Any], path: tuple[str, ...]) -> None:
    value = _require_string(config, path)
    if "user:password@server/database" in value:
        dotted = ".".join(path)
        raise RuntimeError(
            f"Invalid production configuration: {dotted} must not use sample values."
        )


def _extension_enabled(config: Mapping[str, Any], token: str) -> bool:
    extensions = _get_path(config, ("mugen", "modules", "extensions"))
    if not isinstance(extensions, list):
        return False
    normalized_token = token.strip().lower()
    for entry in extensions:
        if not isinstance(entry, Mapping):
            continue
        entry_token = str(entry.get("token", "")).strip().lower()
        if entry_token != normalized_token:
            continue
        raw_enabled = entry.get("enabled", True)
        if isinstance(raw_enabled, str):
            return raw_enabled.strip().lower() not in {"false", "0", "no", "off"}
        return bool(raw_enabled)
    return False


def _validate_cors(config: Mapping[str, Any]) -> None:
    origins = _get_path(config, ("acp", "cors_origins"))
    if not isinstance(origins, list):
        raise RuntimeError(
            "Invalid production configuration: acp.cors_origins is required."
        )
    normalized = [
        origin.strip()
        for origin in origins
        if isinstance(origin, str) and origin.strip() != ""
    ]
    if not normalized:
        raise RuntimeError(
            "Invalid production configuration: acp.cors_origins is required."
        )
    if "*" in normalized:
        raise RuntimeError(
            "Invalid production configuration: acp.cors_origins must not include '*'."
        )


def _validate_acp_secrets(config: Mapping[str, Any]) -> None:
    _require_string(config, ("acp", "secret_key"))
    validate_acp_managed_secret_encryption_key(
        _get_path(
            config,
            ("acp", "key_management", "providers", "managed", "encryption_key"),
        )
    )
    _require_string(config, ("acp", "refresh_token_pepper"))
    _require_string(config, ("acp", "jwt", "active_kid"))
    _require_string(config, ("acp", "jwt", "issuer"))
    _require_string(config, ("acp", "jwt", "audience"))

    keys = _get_path(config, ("acp", "jwt", "keys"))
    if not isinstance(keys, list) or not keys:
        raise RuntimeError(
            "Invalid production configuration: acp.jwt.keys[0] is required."
        )

    active_kid = _require_string(config, ("acp", "jwt", "active_kid"))
    seen_kids: set[str] = set()
    for index, key in enumerate(keys):
        if not isinstance(key, Mapping):
            raise RuntimeError(
                "Invalid production configuration: "
                f"acp.jwt.keys[{index}] must be an object."
            )
        kid = _require_string(key, ("kid",))
        if kid in seen_kids:
            raise RuntimeError(
                "Invalid production configuration: acp.jwt.keys kid values "
                "must be unique."
            )
        seen_kids.add(kid)

        alg = _require_string(key, ("alg",))
        if alg != "EdDSA":
            raise RuntimeError(
                "Invalid production configuration: "
                f"acp.jwt.keys[{index}].alg must be EdDSA."
            )
        pem = _require_string(key, ("pem",))
        if "BEGIN PRIVATE KEY" not in pem or "END PRIVATE KEY" not in pem:
            raise RuntimeError(
                "Invalid production configuration: "
                f"acp.jwt.keys[{index}].pem must be a private PEM."
            )

    if active_kid not in seen_kids:
        raise RuntimeError(
            "Invalid production configuration: "
            "acp.jwt.active_kid must match one configured JWT key."
        )


def _validate_acp_bootstrap_admin(config: Mapping[str, Any]) -> None:
    seed_acp = _get_path(config, ("acp", "seed_acp"))
    if seed_acp is not True:
        return

    _require_string(config, ("acp", "admin_username"))
    _require_string(config, ("acp", "admin_login_email"))
    admin_password = _require_string(config, ("acp", "admin_password"))
    admin_password_hash = _require_string(config, ("acp", "admin_password_hash"))
    if not check_password_hash(admin_password_hash, admin_password):
        raise RuntimeError(
            "Invalid production configuration: "
            "acp.admin_password_hash must match acp.admin_password."
        )


def _selected_gateway_token(config: Mapping[str, Any], gateway_name: str) -> str:
    value = _get_path(
        config,
        ("mugen", "modules", "core", "gateway", gateway_name),
    )
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def _reject_placeholder_if_set(
    config: Mapping[str, Any],
    path: tuple[str, ...],
) -> str:
    value = _get_path(config, path)
    if not isinstance(value, str) or value.strip() == "":
        return ""

    normalized = value.strip()
    if _is_placeholder(normalized):
        dotted = ".".join(path)
        raise RuntimeError(
            "Invalid production configuration: " f"{dotted} must not be a placeholder."
        )
    return normalized


def _validate_optional_credential_pair(
    config: Mapping[str, Any],
    left_path: tuple[str, ...],
    right_path: tuple[str, ...],
) -> bool:
    left = _reject_placeholder_if_set(config, left_path)
    right = _reject_placeholder_if_set(config, right_path)
    if bool(left) != bool(right):
        raise RuntimeError(
            "Invalid production configuration: "
            f"{'.'.join(left_path)} and {'.'.join(right_path)} "
            "must be configured together."
        )
    return bool(left and right)


def _validate_completion_gateway_credentials(config: Mapping[str, Any]) -> None:
    token = _selected_gateway_token(config, "completion")
    required_secret_paths = {
        "azure_foundry": ("azure", "foundry", "api", "key"),
        "cerebras": ("cerebras", "api", "key"),
        "groq": ("groq", "api", "key"),
        "openai": ("openai", "api", "key"),
        "sambanova": ("sambanova", "api", "key"),
    }
    required_path = required_secret_paths.get(token)
    if required_path is not None:
        _require_string(config, required_path)
        return

    if token == "bedrock":
        _validate_optional_credential_pair(
            config,
            ("aws", "bedrock", "api", "access_key_id"),
            ("aws", "bedrock", "api", "secret_access_key"),
        )
        return

    if token == "vertex":
        _reject_placeholder_if_set(config, ("gcp", "vertex", "api", "access_token"))


def _validate_email_gateway_credentials(config: Mapping[str, Any]) -> None:
    token = _selected_gateway_token(config, "email")
    if token == "smtp":
        _validate_optional_credential_pair(
            config,
            ("smtp", "username"),
            ("smtp", "password"),
        )
        return

    if token != "ses":
        return

    credentials_configured = _validate_optional_credential_pair(
        config,
        ("aws", "ses", "api", "access_key_id"),
        ("aws", "ses", "api", "secret_access_key"),
    )
    session_token = _reject_placeholder_if_set(
        config,
        ("aws", "ses", "api", "session_token"),
    )
    if session_token and not credentials_configured:
        raise RuntimeError(
            "Invalid production configuration: "
            "aws.ses.api.session_token requires aws.ses.api access credentials."
        )


def _validate_sms_gateway_credentials(config: Mapping[str, Any]) -> None:
    token = _selected_gateway_token(config, "sms")
    if token != "twilio":
        return

    _require_string(config, ("twilio", "api", "account_sid"))
    auth_token = _reject_placeholder_if_set(
        config,
        ("twilio", "api", "auth_token"),
    )
    api_key_configured = _validate_optional_credential_pair(
        config,
        ("twilio", "api", "api_key_sid"),
        ("twilio", "api", "api_key_secret"),
    )
    if bool(auth_token) == api_key_configured:
        raise RuntimeError(
            "Invalid production configuration: "
            "twilio requires exactly one auth mode."
        )


def _validate_knowledge_gateway_credentials(config: Mapping[str, Any]) -> None:
    token = _selected_gateway_token(config, "knowledge")
    if token == "pinecone":
        _require_string(config, ("pinecone", "api", "key"))
        return

    optional_key_paths = {
        "milvus": ("milvus", "api", "token"),
        "qdrant": ("qdrant", "api", "key"),
        "weaviate": ("weaviate", "api", "key"),
    }
    optional_path = optional_key_paths.get(token)
    if optional_path is not None:
        _reject_placeholder_if_set(config, optional_path)


def _validate_selected_gateway_credentials(config: Mapping[str, Any]) -> None:
    _validate_completion_gateway_credentials(config)
    _validate_email_gateway_credentials(config)
    _validate_sms_gateway_credentials(config)
    _validate_knowledge_gateway_credentials(config)


def validate_production_deployment_config(config: Mapping[str, Any]) -> None:
    """Validate resolved deployment config when environment is production."""
    if not _is_production_environment(config):
        return

    _require_database_url(config, ("rdbms", "alembic", "url"))
    _require_database_url(config, ("rdbms", "sqlalchemy", "url"))
    validate_quart_secret_key(_get_path(config, ("quart", "secret_key")))

    if _extension_enabled(config, "core.fw.acp"):
        _validate_cors(config)
        _validate_acp_secrets(config)
        _validate_acp_bootstrap_admin(config)

    _validate_selected_gateway_credentials(config)

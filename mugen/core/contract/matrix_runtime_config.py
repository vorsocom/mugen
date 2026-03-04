"""Strict runtime config contract checks for matrix-enabled core deployments."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MATRIX_DEVICE_TRUST_MODE_STRICT_KNOWN = "strict_known"
MATRIX_DEVICE_TRUST_MODE_ALLOWLIST = "allowlist"
MATRIX_DEVICE_TRUST_MODE_PERMISSIVE = "permissive"
MATRIX_DEVICE_TRUST_MODES = frozenset(
    {
        MATRIX_DEVICE_TRUST_MODE_STRICT_KNOWN,
        MATRIX_DEVICE_TRUST_MODE_ALLOWLIST,
        MATRIX_DEVICE_TRUST_MODE_PERMISSIVE,
    }
)


def _require_table(parent: object, *, path: str) -> Mapping[str, Any]:
    if not isinstance(parent, Mapping):
        raise RuntimeError(f"Invalid configuration: {path} must be a table.")
    return parent


def _require_non_empty_string(*, value: object, path: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise RuntimeError(
            f"Invalid configuration: {path} is required and must be a non-empty string."
        )
    return value.strip()


def _require_non_empty_string_list(*, value: object, path: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise RuntimeError(
            f"Invalid configuration: {path} must be a non-empty array of strings."
        )
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or item.strip() == "":
            raise RuntimeError(
                f"Invalid configuration: {path}[{index}] must be a non-empty string."
            )
        normalized.append(item.strip())
    return normalized


def _require_string_list(*, value: object, path: str) -> list[str]:
    if not isinstance(value, list):
        raise RuntimeError(
            f"Invalid configuration: {path} must be an array of strings."
        )
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or item.strip() == "":
            raise RuntimeError(
                f"Invalid configuration: {path}[{index}] must be a non-empty string."
            )
        normalized.append(item.strip())
    return normalized


def _require_bool(*, value: object, path: str) -> bool:
    if isinstance(value, bool) is not True:
        raise RuntimeError(f"Invalid configuration: {path} must be a boolean.")
    return value


def _require_positive_int(*, value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(
            f"Invalid configuration: {path} must be a positive integer."
        )
    if value <= 0:
        raise RuntimeError(
            f"Invalid configuration: {path} must be a positive integer."
        )
    return value


def _validate_matrix_device_trust_allowlist(*, allowlist: object) -> None:
    if not isinstance(allowlist, list):
        raise RuntimeError(
            "Invalid configuration: matrix.security.device_trust.allowlist "
            "must be an array."
        )
    if not allowlist:
        raise RuntimeError(
            "Invalid configuration: matrix.security.device_trust.allowlist "
            "must be a non-empty array when mode=allowlist."
        )

    for index, entry in enumerate(allowlist):
        if not isinstance(entry, Mapping):
            raise RuntimeError(
                "Invalid configuration: matrix.security.device_trust.allowlist"
                f"[{index}] must be a table."
            )
        user_id = entry.get("user_id")
        if not isinstance(user_id, str) or user_id.strip() == "":
            raise RuntimeError(
                "Invalid configuration: matrix.security.device_trust.allowlist"
                f"[{index}].user_id must be a non-empty string."
            )
        device_ids = entry.get("device_ids")
        _require_non_empty_string_list(
            value=device_ids,
            path=f"matrix.security.device_trust.allowlist[{index}].device_ids",
        )


def validate_matrix_enabled_runtime_config(config: Mapping[str, Any]) -> None:
    """Validate strict matrix runtime config when matrix platform is enabled."""
    matrix_cfg = _require_table(config.get("matrix"), path="matrix")

    _require_non_empty_string(
        value=matrix_cfg.get("homeserver"),
        path="matrix.homeserver",
    )

    client_cfg = _require_table(matrix_cfg.get("client"), path="matrix.client")
    _require_non_empty_string(
        value=client_cfg.get("user"),
        path="matrix.client.user",
    )
    _require_non_empty_string(
        value=client_cfg.get("password"),
        path="matrix.client.password",
    )

    domains_cfg = _require_table(matrix_cfg.get("domains"), path="matrix.domains")
    _require_non_empty_string_list(
        value=domains_cfg.get("allowed"),
        path="matrix.domains.allowed",
    )
    _require_string_list(
        value=domains_cfg.get("denied"),
        path="matrix.domains.denied",
    )

    invites_cfg = _require_table(matrix_cfg.get("invites"), path="matrix.invites")
    _require_bool(
        value=invites_cfg.get("direct_only"),
        path="matrix.invites.direct_only",
    )

    media_cfg = _require_table(matrix_cfg.get("media"), path="matrix.media")
    _require_non_empty_string_list(
        value=media_cfg.get("allowed_mimetypes"),
        path="matrix.media.allowed_mimetypes",
    )
    _require_positive_int(
        value=media_cfg.get("max_download_bytes"),
        path="matrix.media.max_download_bytes",
    )

    matrix_security_cfg = _require_table(
        matrix_cfg.get("security"),
        path="matrix.security",
    )
    device_trust_cfg = _require_table(
        matrix_security_cfg.get("device_trust"),
        path="matrix.security.device_trust",
    )
    mode = _require_non_empty_string(
        value=device_trust_cfg.get("mode"),
        path="matrix.security.device_trust.mode",
    ).lower()
    if mode not in MATRIX_DEVICE_TRUST_MODES:
        supported_modes = ", ".join(sorted(MATRIX_DEVICE_TRUST_MODES))
        raise RuntimeError(
            "Invalid configuration: matrix.security.device_trust.mode "
            f"must be one of: {supported_modes}."
        )
    if mode == MATRIX_DEVICE_TRUST_MODE_ALLOWLIST:
        _validate_matrix_device_trust_allowlist(
            allowlist=device_trust_cfg.get("allowlist"),
        )

    security_cfg = config.get("security")
    secrets_cfg = (
        security_cfg.get("secrets")
        if isinstance(security_cfg, Mapping)
        else None
    )
    encryption_key = (
        secrets_cfg.get("encryption_key")
        if isinstance(secrets_cfg, Mapping)
        else None
    )
    if not isinstance(encryption_key, str) or encryption_key.strip() == "":
        raise RuntimeError(
            "Invalid configuration: security.secrets.encryption_key is required "
            "when matrix platform is enabled."
        )

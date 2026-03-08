"""Helpers for live multi-profile platform runtime reloads."""

from __future__ import annotations

__all__ = [
    "PROFILED_RUNTIME_PLATFORMS",
    "PlatformRuntimeProfileReloadError",
    "reload_platform_runtime_profiles",
]

from collections.abc import Iterable, Mapping
from types import SimpleNamespace
from typing import Any

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.di.injector import DependencyInjector
from mugen.core.utility.platform_runtime_profile import build_config_namespace
from mugen.core.utility.platforms import normalize_platforms

PROFILED_RUNTIME_PLATFORMS = (
    "line",
    "matrix",
    "signal",
    "telegram",
    "wechat",
    "whatsapp",
)

_PLATFORM_CLIENT_ATTRS = {
    "line": "line_client",
    "matrix": "matrix_client",
    "signal": "signal_client",
    "telegram": "telegram_client",
    "wechat": "wechat_client",
    "whatsapp": "whatsapp_client",
}

_CONFIG_AWARE_PROVIDER_ATTRS = (
    "completion_gateway",
    "context_engine_service",
    "email_gateway",
    "ipc_service",
    "keyval_storage_gateway",
    "knowledge_gateway",
    "media_storage_gateway",
    "messaging_service",
    "nlp_service",
    "platform_service",
    "sms_gateway",
    "user_service",
    "web_client",
    "web_runtime_store",
    *_PLATFORM_CLIENT_ATTRS.values(),
)


class PlatformRuntimeProfileReloadError(RuntimeError):
    """Raised when a live runtime-profile reload cannot complete safely."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 409,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.details = dict(details or {})


def _logger_from_injector(injector: DependencyInjector) -> ILoggingGateway | None:
    logger = getattr(injector, "logging_gateway", None)
    if logger is None:
        return None
    return logger


def _config_dict(config: Mapping[str, Any] | SimpleNamespace | None) -> dict[str, Any]:
    if isinstance(config, Mapping):
        return dict(config)
    if isinstance(config, SimpleNamespace):
        raw = getattr(config, "dict", None)
        if isinstance(raw, Mapping):
            return dict(raw)
    raise PlatformRuntimeProfileReloadError(
        "Container configuration payload is unavailable.",
        status_code=500,
    )


def _resolve_config_file(config_file: str | None = None) -> str:
    if config_file is None:
        return di._resolve_config_file()  # pylint: disable=protected-access

    normalized = str(config_file).strip()
    if normalized == "":
        raise PlatformRuntimeProfileReloadError(
            "config_file must be a non-empty string when provided.",
            status_code=400,
        )
    return normalized


def _active_platforms(config: Mapping[str, Any] | SimpleNamespace) -> tuple[str, ...]:
    config_dict = _config_dict(config)
    mugen_cfg = config_dict.get("mugen", {})
    if not isinstance(mugen_cfg, Mapping):
        return ()
    return tuple(normalize_platforms(mugen_cfg.get("platforms", [])))


def _platform_config_snapshot(
    config: Mapping[str, Any] | SimpleNamespace,
    *,
    platform: str,
) -> Any:
    config_dict = _config_dict(config)
    return config_dict.get(str(platform).strip().lower())


def _profile_config_changed(
    current_config: Mapping[str, Any] | SimpleNamespace,
    next_config: Mapping[str, Any] | SimpleNamespace,
    *,
    platform: str,
) -> bool:
    return _platform_config_snapshot(
        current_config,
        platform=platform,
    ) != _platform_config_snapshot(
        next_config,
        platform=platform,
    )


def _unchanged_profile_diff(
    injector: DependencyInjector | None,
    *,
    platform: str,
) -> dict[str, list[str]]:
    unchanged: list[str] = []
    client_attr = _PLATFORM_CLIENT_ATTRS.get(platform)
    client = getattr(injector, client_attr, None) if client_attr is not None else None
    configured_ids = getattr(client, "configured_client_profile_ids", None)
    if callable(configured_ids):
        result = configured_ids()
        if isinstance(result, tuple | list):
            unchanged = [
                str(item)
                for item in result
                if str(item).strip() != ""
            ]
    if not unchanged:
        managed_clients = getattr(client, "managed_clients", None)
        if callable(managed_clients):
            managed = managed_clients()
            if isinstance(managed, Mapping):
                unchanged = sorted(
                    str(item)
                    for item in managed.keys()
                    if str(item).strip() != ""
                )
    return {
        "added": [],
        "removed": [],
        "updated": [],
        "unchanged": unchanged,
    }


def _normalize_reload_diff(
    diff: object,
    *,
    injector: DependencyInjector | None,
    platform: str,
) -> dict[str, list[str]]:
    if not isinstance(diff, Mapping):
        return _unchanged_profile_diff(injector, platform=platform)

    normalized = _unchanged_profile_diff(injector, platform=platform)
    for key in ("added", "removed", "updated", "unchanged"):
        values = diff.get(key, normalized[key])
        if not isinstance(values, Iterable) or isinstance(
            values,
            str | bytes | Mapping,
        ):
            values = normalized[key]
        normalized[key] = [str(value) for value in values]
    return normalized


def _normalize_requested_platforms(
    platforms: Iterable[str] | None,
) -> set[str] | None:
    if platforms is None:
        return None
    normalized: set[str] = set()
    for value in platforms:
        platform = str(value or "").strip().lower()
        if platform in PROFILED_RUNTIME_PLATFORMS:
            normalized.add(platform)
    return normalized


def _iter_extension_collections(node: object) -> Iterable[list[Any]]:
    for attr in (
        "_cp_extensions",
        "_ct_extensions",
        "_ipc_extensions",
        "_mh_extensions",
        "_rpp_extensions",
    ):
        value = getattr(node, attr, None)
        if isinstance(value, list):
            yield value


def _refresh_runtime_config_reference(
    node: object,
    *,
    injector: DependencyInjector,
    config: SimpleNamespace,
    seen: set[int],
) -> None:
    if node is None:
        return

    node_id = id(node)
    if node_id in seen:
        return
    seen.add(node_id)

    if hasattr(node, "_config"):
        try:
            setattr(node, "_config", config)
        except Exception:  # pylint: disable=broad-exception-caught
            ...

    platforms = getattr(node, "platforms", None)
    if isinstance(platforms, list) and len(platforms) == 1:
        platform = str(platforms[0] or "").strip().lower()
        client_attr = _PLATFORM_CLIENT_ATTRS.get(platform)
        if client_attr is not None and hasattr(node, "_client"):
            try:
                setattr(node, "_client", getattr(injector, client_attr, None))
            except Exception:  # pylint: disable=broad-exception-caught
                ...

    refresh_runtime_config = getattr(node, "refresh_runtime_config", None)
    if callable(refresh_runtime_config):
        refresh_runtime_config(config=config)

    if hasattr(node, "_event_dedup_ttl_seconds"):
        resolver = getattr(node, "_resolve_event_dedup_ttl_seconds", None)
        if callable(resolver):
            try:
                node._event_dedup_ttl_seconds = resolver()  # pylint: disable=protected-access
            except Exception:  # pylint: disable=broad-exception-caught
                ...

    if hasattr(node, "_typing_enabled"):
        resolver = getattr(node, "_resolve_typing_enabled", None)
        if callable(resolver):
            try:
                node._typing_enabled = resolver()  # pylint: disable=protected-access
            except Exception:  # pylint: disable=broad-exception-caught
                ...

    for collection in _iter_extension_collections(node):
        for child in collection:
            _refresh_runtime_config_reference(
                child,
                injector=injector,
                config=config,
                seen=seen,
            )


def _refresh_runtime_config_references(
    injector: DependencyInjector,
    *,
    config: SimpleNamespace,
) -> None:
    injector.config = config
    seen: set[int] = {id(injector)}
    for attr in _CONFIG_AWARE_PROVIDER_ATTRS:
        _refresh_runtime_config_reference(
            getattr(injector, attr, None),
            injector=injector,
            config=config,
            seen=seen,
        )


async def reload_platform_runtime_profiles(
    *,
    injector: DependencyInjector,
    logger: ILoggingGateway | None = None,
    config_file: str | None = None,
    platforms: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Reload all configured multi-profile platform runtimes in place."""
    if not isinstance(injector, DependencyInjector):
        raise PlatformRuntimeProfileReloadError(
            "Live runtime reload requires a valid dependency injector.",
            status_code=500,
        )

    resolved_logger = logger if logger is not None else _logger_from_injector(injector)
    current_config = getattr(injector, "config", None)
    current_config_dict = _config_dict(current_config)
    current_active_platforms = set(_active_platforms(current_config_dict))

    resolved_config_file = _resolve_config_file(config_file)
    next_config_dict = di._load_config(resolved_config_file)  # pylint: disable=protected-access
    di._validate_core_module_schema(next_config_dict)  # pylint: disable=protected-access
    next_config = build_config_namespace(next_config_dict)
    next_active_platforms = set(_active_platforms(next_config_dict))

    activation_changes = sorted(
        platform
        for platform in PROFILED_RUNTIME_PLATFORMS
        if (platform in current_active_platforms) != (platform in next_active_platforms)
    )
    if activation_changes:
        change_text = ", ".join(activation_changes)
        raise PlatformRuntimeProfileReloadError(
            "Platform activation changes require a restart. "
            f"Changed platforms: {change_text}.",
            status_code=409,
            details={"activation_changes": activation_changes},
        )

    requested_platforms = _normalize_requested_platforms(platforms)
    if requested_platforms is None:
        target_platforms = {
            platform
            for platform in next_active_platforms
            if _profile_config_changed(
                current_config_dict,
                next_config_dict,
                platform=platform,
            )
        }
    else:
        target_platforms = requested_platforms & next_active_platforms

    platform_results: dict[str, dict[str, Any]] = {}
    reloaded_platforms: list[str] = []

    try:
        for platform in PROFILED_RUNTIME_PLATFORMS:
            if platform not in next_active_platforms:
                continue

            if platform not in target_platforms:
                diff = _unchanged_profile_diff(injector, platform=platform)
                platform_results[platform] = {
                    "status": "unchanged",
                    "added": list(diff["added"]),
                    "removed": list(diff["removed"]),
                    "updated": list(diff["updated"]),
                    "unchanged": list(diff["unchanged"]),
                }
                continue

            client_attr = _PLATFORM_CLIENT_ATTRS[platform]
            client = getattr(injector, client_attr, None)
            if client is None:
                raise PlatformRuntimeProfileReloadError(
                    f"Runtime client is unavailable for active platform {platform!r}.",
                    status_code=500,
                )

            reload_profiles = getattr(client, "reload_profiles", None)
            if not callable(reload_profiles):
                raise PlatformRuntimeProfileReloadError(
                    f"Runtime client does not support live profile reload for "
                    f"platform {platform!r}.",
                    status_code=500,
                )

            diff = _normalize_reload_diff(
                await reload_profiles(next_config),
                injector=injector,
                platform=platform,
            )
            status = "reloaded"
            if (
                len(diff.get("added", [])) == 0
                and len(diff.get("removed", [])) == 0
                and len(diff.get("updated", [])) == 0
            ):
                status = "unchanged"
            platform_results[platform] = {
                "status": status,
                "added": list(diff.get("added", [])),
                "removed": list(diff.get("removed", [])),
                "updated": list(diff.get("updated", [])),
                "unchanged": list(diff.get("unchanged", [])),
            }
            if status == "reloaded":
                reloaded_platforms.append(platform)

        _refresh_runtime_config_references(injector, config=next_config)
    except Exception as exc:
        rollback_failures: dict[str, str] = {}
        for platform in reversed(reloaded_platforms):
            client = getattr(injector, _PLATFORM_CLIENT_ATTRS[platform], None)
            rollback = getattr(client, "reload_profiles", None)
            if not callable(rollback):
                rollback_failures[platform] = "rollback unavailable"
                continue
            try:
                await rollback(current_config)
                platform_results[platform]["rollback_status"] = "restored"
            except Exception as rollback_exc:  # pylint: disable=broad-exception-caught
                rollback_failures[platform] = (
                    f"{type(rollback_exc).__name__}: {rollback_exc}"
                )

        _refresh_runtime_config_references(injector, config=current_config)

        if isinstance(exc, PlatformRuntimeProfileReloadError):
            details = dict(exc.details)
            details["platform_results"] = platform_results
            if rollback_failures:
                details["rollback_failures"] = rollback_failures
            raise PlatformRuntimeProfileReloadError(
                str(exc),
                status_code=exc.status_code,
                details=details,
            ) from exc

        raise PlatformRuntimeProfileReloadError(
            "Live runtime profile reload failed "
            f"({type(exc).__name__}: {exc}).",
            status_code=409,
            details={
                "platform_results": platform_results,
                "rollback_failures": rollback_failures,
            },
        ) from exc

    if resolved_logger is not None:
        changed_platforms = [
            platform
            for platform, result in platform_results.items()
            if result.get("status") == "reloaded"
        ]
        resolved_logger.info(
            "Reloaded platform runtime profiles "
            f"config_file={resolved_config_file!r} "
            f"changed_platforms={changed_platforms}."
        )

    return {
        "config_file": resolved_config_file,
        "active_platforms": sorted(next_active_platforms),
        "platforms": platform_results,
    }

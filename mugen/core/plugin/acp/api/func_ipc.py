"""Implements IPC related API endpoints."""

from types import SimpleNamespace
from typing import Any

from quart import abort, request

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.ipc import IIPCService, IPCCommandRequest
from mugen.core.plugin.acp.api.decorator.auth import global_admin_required

_default_acp_ipc_timeout_seconds = 10.0

_default_acp_ipc_timeout_max_seconds = 30.0


def _config_provider():
    return di.container.config


def _ipc_provider():
    return di.container.ipc_service


def _logger_provider():
    return di.container.logging_gateway


@api.post("/core/acp/v1/ipc")
@global_admin_required
async def ipc_webhook(
    config_provider=_config_provider,
    ipc_provider=_ipc_provider,
    logger_provider=_logger_provider,
    **_,
) -> dict:
    """Handle IPC calls."""
    config: SimpleNamespace = config_provider()
    ipc_service: IIPCService = ipc_provider()
    logger: ILoggingGateway = logger_provider()
    auth_user = _.get("auth_user")

    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    command = data.get("command")
    platform = data.get("platform")
    if not isinstance(command, str) or command.strip() == "":
        logger.debug("Missing/invalid command in IPC webhook payload.")
        abort(400)
    if not isinstance(platform, str) or platform.strip() == "":
        logger.debug("Missing/invalid platform in IPC webhook payload.")
        abort(400)

    normalized_command = command.strip()
    normalized_platform = platform.strip()
    if not _command_allowed(
        config,
        platform=normalized_platform,
        command=normalized_command,
    ):
        logger.warning(
            "Unauthorized IPC command invocation"
            f" auth_user={auth_user}"
            f" platform={normalized_platform}"
            f" command={normalized_command}"
        )
        abort(403, "IPC command not allowed.")

    payload_data = data.get("data")
    if payload_data is None:
        payload_data = {}
    if not isinstance(payload_data, dict):
        logger.debug("Invalid IPC data payload.")
        abort(400)

    timeout_seconds = _resolve_timeout_seconds(
        config,
        data.get("timeout_seconds"),
    )
    if timeout_seconds is None:
        logger.debug("Missing parameter(s) in IPC webhook payload.")
        abort(400)

    response = await ipc_service.handle_ipc_request(
        IPCCommandRequest(
            platform=normalized_platform,
            command=normalized_command,
            data=payload_data,
            timeout_seconds=timeout_seconds,
        )
    )
    response_payload = response.to_dict()
    logger.info(
        "ACP IPC dispatch"
        f" auth_user={auth_user}"
        f" platform={normalized_platform}"
        f" command={normalized_command}"
        f" duration_ms={response_payload['duration_ms']}"
        f" expected_handlers={response_payload['expected_handlers']}"
        f" received={response_payload['received']}"
        f" error_count={len(response_payload['errors'])}"
    )
    return {
        "response": response_payload,
    }


def _command_allowed(
    config: SimpleNamespace,
    *,
    platform: str,
    command: str,
) -> bool:
    allowlist = getattr(
        getattr(getattr(config, "acp", SimpleNamespace()), "ipc", SimpleNamespace()),
        "allowed_commands",
        [],
    )
    if not isinstance(allowlist, list):
        return False
    normalized = [str(item).strip() for item in allowlist if str(item).strip() != ""]
    if not normalized:
        return False
    command_key = f"{platform}:{command}"
    return command_key in normalized


def _resolve_timeout_seconds(
    config: SimpleNamespace,
    raw_timeout: Any,
) -> float | None:
    acp_ipc_cfg = getattr(getattr(config, "acp", SimpleNamespace()), "ipc", None)
    default_timeout = _coerce_positive_float(
        getattr(acp_ipc_cfg, "timeout_seconds", _default_acp_ipc_timeout_seconds),
        fallback=_default_acp_ipc_timeout_seconds,
    )
    max_timeout = _coerce_positive_float(
        getattr(
            acp_ipc_cfg,
            "max_timeout_seconds",
            _default_acp_ipc_timeout_max_seconds,
        ),
        fallback=_default_acp_ipc_timeout_max_seconds,
    )
    if max_timeout < default_timeout:
        max_timeout = default_timeout
    if raw_timeout in [None, ""]:
        return default_timeout
    parsed = _coerce_positive_float(raw_timeout, fallback=None)
    if parsed is None:
        return None
    if parsed > max_timeout:
        return max_timeout
    return parsed


def _coerce_positive_float(raw_value: Any, fallback: float | None) -> float | None:
    try:
        parsed = float(raw_value)
    except (TypeError, ValueError):
        return fallback
    if parsed <= 0:
        return fallback
    return parsed

"""Implements webhook endpoints for the Telegram Bot API."""

from quart import abort, request

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.ipc import IIPCService, IPCCommandRequest
from mugen.core.plugin.telegram.botapi.api.decorator import (
    telegram_platform_required,
    telegram_webhook_path_token_required,
    telegram_webhook_secret_required,
)


def _config_provider():
    return di.container.config


def _ipc_provider():
    return di.container.ipc_service


def _logger_provider():
    return di.container.logging_gateway


@api.post("/telegram/botapi/webhook/<path_token>")
@telegram_platform_required
@telegram_webhook_path_token_required
@telegram_webhook_secret_required
async def telegram_botapi_webhook_event(
    path_token: str,
    ipc_provider=_ipc_provider,
    logger_provider=_logger_provider,
):
    """Respond to Telegram Bot API webhook events."""
    _ = path_token

    ipc_svc: IIPCService = ipc_provider()
    logger: ILoggingGateway = logger_provider()

    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    response = await ipc_svc.handle_ipc_request(
        IPCCommandRequest(
            platform="telegram",
            command="telegram_botapi_update",
            data=data,
        )
    )
    if response.errors:
        logger.warning(
            "Telegram webhook processed with IPC errors"
            " command=telegram_botapi_update"
            f" error_count={len(response.errors)}"
        )
    return {"response": "OK"}

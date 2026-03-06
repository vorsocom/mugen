"""Implements webhook endpoints for the LINE Messaging API."""

from quart import abort, request

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.ipc import IIPCService, IPCCommandRequest
from mugen.core.plugin.line.messagingapi.api.decorator import (
    line_platform_required,
    line_webhook_path_token_required,
    line_webhook_signature_required,
)


def _config_provider():
    return di.container.config


def _ipc_provider():
    return di.container.ipc_service


def _logger_provider():
    return di.container.logging_gateway


@api.post("/line/messagingapi/webhook/<path_token>")
@line_platform_required
@line_webhook_path_token_required
@line_webhook_signature_required
async def line_messagingapi_webhook_event(
    path_token: str,
    ipc_provider=_ipc_provider,
    logger_provider=_logger_provider,
):
    """Respond to LINE Messaging API webhook events."""

    ipc_svc: IIPCService = ipc_provider()
    logger: ILoggingGateway = logger_provider()

    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    response = await ipc_svc.handle_ipc_request(
        IPCCommandRequest(
            platform="line",
            command="line_messagingapi_event",
            data={
                "path_token": path_token,
                "payload": data,
            },
        )
    )
    if response.errors:
        logger.warning(
            "LINE webhook processed with IPC errors"
            " command=line_messagingapi_event"
            f" error_count={len(response.errors)}"
        )
    return {"response": "OK"}

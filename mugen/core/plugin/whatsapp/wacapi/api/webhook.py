"""
Implements webhook endpoints for the WhatsApp Cloud API (WACAPI).
"""

import asyncio
from types import SimpleNamespace

from quart import abort, request

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.plugin.whatsapp.wacapi.api.decorator import (
    whatsapp_platform_required,
    whatsapp_request_signature_verification_required,
    whatsapp_server_ip_allow_list_required,
)


def _config_provider():
    return di.container.config


def _ipc_provider():
    return di.container.ipc_service


def _logger_provider():
    return di.container.logging_gateway


@api.get("/whatsapp/wacapi/webhook")
@whatsapp_platform_required
@whatsapp_server_ip_allow_list_required
async def whatsapp_wacapi_subscription(
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Whatsapp Cloud API verification."""
    config: SimpleNamespace = config_provider()
    logger: ILoggingGateway = logger_provider()

    if request.args.get("hub.mode") != "subscribe":
        logger.error("hub.mode incorrect.")
        abort(400)

    if request.args.get("hub.verify_token") in [None, ""]:
        logger.error("hub.verify_token not supplied or is empty.")
        abort(400)

    try:
        if (
            request.args.get("hub.verify_token")
            != config.whatsapp.webhook.verification_token
        ):
            logger.error("Incorrect verification token.")
            abort(400)
    except AttributeError:
        logger.error("Could not get verification token.")
        abort(500)

    if request.args.get("hub.challenge") in [None, ""]:
        logger.error("hub.challenge not supplied or is empty.")
        abort(400)

    return request.args.get("hub.challenge")


@api.post("/whatsapp/wacapi/webhook")
@whatsapp_platform_required
@whatsapp_server_ip_allow_list_required
@whatsapp_request_signature_verification_required
async def whatsapp_wacapi_event(
    ipc_provider=_ipc_provider,
    logger_provider=_logger_provider,
):
    """Respond to Whatsapp Cloud API events."""
    # Get request data.
    # get_json was not used to make code more
    # cosistent with signature verification decorator
    # for testing.
    ipc_svc: IIPCService = ipc_provider()
    logger: ILoggingGateway = logger_provider()

    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    # Queue allowing IPC queue consumer to send back a response.
    response_queue = asyncio.Queue()

    await ipc_svc.handle_ipc_request(
        "whatsapp",
        {
            "response_queue": response_queue,
            "command": "whatsapp_wacapi_event",
            "data": data,
        },
    )

    try:
        response = await asyncio.wait_for(response_queue.get(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.error("Timed out waiting for IPC response on 'whatsapp'.")
        abort(504)

    return response

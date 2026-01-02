"""Implements IPC related API endpoints."""

import asyncio

from quart import abort, request

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.ipc import IIPCService
from mugen.core.plugin.acp.api.decorator.auth import global_auth_required


@api.post("/core/acp/v1/ipc")
@global_auth_required
async def ipc_webhook(
    ipc_provider=lambda: di.container.ipc_service,
    logger_provider=lambda: di.container.logging_gateway,
    **_,
) -> dict:
    """Handle IPC calls."""
    ipc_service: IIPCService = ipc_provider()
    logger: ILoggingGateway = logger_provider()

    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    command: str = data.get("command")
    platform: str = data.get("platform")
    if not command or not platform:
        logger.debug("Missing parameter(s) in IPC webhook payload.")
        abort(400)

    # Queue allowing IPC queue consumer to send back a response.
    response_queue = asyncio.Queue()

    await ipc_service.handle_ipc_request(
        platform,
        {
            "response_queue": response_queue,
            "command": command,
            "data": data,
        },
    )

    try:
        response = await asyncio.wait_for(response_queue.get(), timeout=10.0)
    except asyncio.TimeoutError:
        logger.error("Timed out waiting for IPC response on 'matrix'.")
        abort(504)

    return response

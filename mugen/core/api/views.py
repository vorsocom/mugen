"""Implements API endpoints."""

import asyncio

from quart import abort, current_app, request

from mugen.core.api import api
from mugen.core.api.decorators import (
    matrix_platform_required,
    whatsapp_platform_required,
    whatsapp_request_signature_verification_required,
    whatsapp_server_ip_allow_list_required,
)
from mugen.core.contract.service.ipc import IIPCService


@api.get("/matrix")
@matrix_platform_required
async def matrix_index():
    """Matrix index endpoint."""
    # Get the IPC service from the dependency injector.
    ipc_service: IIPCService = current_app.di.ipc_service()

    # Queue allowing IPC queue consumer to send back a response.
    response_queue = asyncio.Queue()

    await ipc_service.handle_ipc_request(
        "matrix",
        {
            "response_queue": response_queue,
            "command": "matrix_get_status",
        },
    )

    # Ensure other tasks can run,
    # otherwise no response will be sent back.
    while response_queue.empty():
        await asyncio.sleep(0)

    # Get the response from the response queue.
    response = await response_queue.get()
    return {"status": response["response"]}


@api.put("/matrix/webhook")
@matrix_platform_required
async def matrix_cron():
    """Handle IPC calls for the Matrix platform."""
    # Get request data.
    data = await request.get_json()

    if "command" not in data.keys() or data["command"] == "":
        abort(400)

    # Get the IPC service from the dependency injector.
    ipc_service: IIPCService = current_app.di.ipc_service()

    # Queue allowing IPC queue consumer to send back a response.
    response_queue = asyncio.Queue()

    await ipc_service.handle_ipc_request(
        "matrix",
        {
            "response_queue": response_queue,
            "command": data["command"],
            "data": data,
        },
    )

    # Ensure other tasks can run,
    # otherwise no response will be sent back.
    while response_queue.empty():
        await asyncio.sleep(0)

    # Get the response from the response queue.
    response = await response_queue.get()
    return response


@api.get("/whatsapp")
@whatsapp_platform_required
async def whatsapp_index():
    """Whatsapp index endpoint."""
    # Get the IPC service from the dependency injector.
    ipc_service: IIPCService = current_app.di.ipc_service()

    # Queue allowing IPC queue consumer to send back a response.
    response_queue = asyncio.Queue()

    await ipc_service.handle_ipc_request(
        "whatsapp",
        {
            "response_queue": response_queue,
            "command": "whatsapp_get_status",
        },
    )

    # Ensure other tasks can run,
    # otherwise no response will be sent back.
    while response_queue.empty():
        await asyncio.sleep(0)

    # Get the response from the response queue.
    response = await response_queue.get()
    return {"status": response["response"]}


@api.get("/whatsapp/wacapi/webhook")
@whatsapp_platform_required
@whatsapp_server_ip_allow_list_required
async def whatsapp_wcapi_verification():
    """Whatsapp Cloud API verification."""
    if (
        request.args.get("hub.mode") == "subscribe"
        and request.args.get("hub.verify_token")
        == current_app.config["ENV"].whatsapp.webhook.verification_token()
    ):
        return request.args.get("hub.challenge")
    abort(400)


@api.post("/whatsapp/wacapi/webhook")
@whatsapp_platform_required
@whatsapp_server_ip_allow_list_required
@whatsapp_request_signature_verification_required
async def whatsapp_wcapi_webhook():
    """Respond to Whatsapp Cloud API events."""
    # Get request data.
    data = await request.get_json()

    # Get the IPC service from the dependency injector.
    ipc_service: IIPCService = current_app.di.ipc_service()

    # Queue allowing IPC queue consumer to send back a response.
    response_queue = asyncio.Queue()

    await ipc_service.handle_ipc_request(
        "whatsapp",
        {
            "response_queue": response_queue,
            "command": "whatsapp_wacapi_event",
            "data": data,
        },
    )

    # Ensure other tasks can run,
    # otherwise no response will be sent back.
    while response_queue.empty():
        await asyncio.sleep(0)

    # Get the response from the response queue.
    response = await response_queue.get()
    return response


@api.put("/whatsapp/webhook")
@whatsapp_platform_required
async def whatsapp_webhook():
    """Handle IPC calls for the WhatsApp platform."""
    # Get request data.
    data = await request.get_json()

    if "command" not in data.keys() or data["command"] == "":
        abort(400)

    # Get the IPC service from the dependency injector.
    ipc_service: IIPCService = current_app.di.ipc_service()

    # Queue allowing IPC queue consumer to send back a response.
    response_queue = asyncio.Queue()

    await ipc_service.handle_ipc_request(
        "whatsapp",
        {
            "response_queue": response_queue,
            "command": data["command"],
            "data": data,
        },
    )

    # Ensure other tasks can run,
    # otherwise no response will be sent back.
    while response_queue.empty():
        await asyncio.sleep(0)

    # Get the response from the response queue.
    response = await response_queue.get()
    return response

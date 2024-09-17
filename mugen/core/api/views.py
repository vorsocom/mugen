"""Implements API endpoints."""

import asyncio

from quart import abort, current_app, request

from mugen.core.api import api_bp
from mugen.core.api.decorators import (
    matrix_platform_required,
    whatsapp_platform_required,
    whatsapp_request_signature_verification_required,
    whatsapp_server_ip_allow_list_required,
)


@api_bp.get("/matrix")
@matrix_platform_required
async def matrix_index():
    """Matrix index endpoint."""
    # Get the IPC queue from the applicaiton object.
    ipc_queue: asyncio.Queue = current_app.matrix_ipc_queue

    # Queue allowing IPC queue consumer to send back a response.
    response_queue = asyncio.Queue()

    # Put payload into IPC queue.
    await ipc_queue.put(
        {
            "response_queue": response_queue,
            "command": "matrix_get_status",
        }
    )

    # Ensure other tasks can run,
    # otherwise no response will be sent back.
    while response_queue.empty():
        await asyncio.sleep(0.01)

    # Get the response from the response queue.
    response = await response_queue.get()
    return {"status": response["response"]}


@api_bp.put("/matrix/webhook")
@matrix_platform_required
async def matrix_cron():
    """Handle IPC calls for the Matrix platform."""
    # Get request data.
    data = await request.get_json()

    if "command" not in data.keys() or data["command"] == "":
        abort(400)

    # Get the IPC queue from the applicaiton object.
    ipc_queue: asyncio.Queue = current_app.matrix_ipc_queue

    # Queue allowing IPC queue consumer to send back a response.
    response_queue = asyncio.Queue()

    # Put payload into IPC queue.
    await ipc_queue.put(
        {
            "response_queue": response_queue,
            "command": data["command"],
            "data": data,
        }
    )

    # Ensure other tasks can run,
    # otherwise no response will be sent back.
    while response_queue.empty():
        await asyncio.sleep(0.01)

    # Get the response from the response queue.
    response = await response_queue.get()
    return response


@api_bp.get("/whatsapp")
@whatsapp_platform_required
async def whatsapp_index():
    """Whatsapp index endpoint."""
    # Get the IPC queue from the applicaiton object.
    ipc_queue: asyncio.Queue = current_app.whatsapp_ipc_queue

    # Queue allowing IPC queue consumer to send back a response.
    response_queue = asyncio.Queue()

    # Put payload into IPC queue.
    await ipc_queue.put(
        {
            "response_queue": response_queue,
            "command": "whatsapp_get_status",
        }
    )

    # Ensure other tasks can run,
    # otherwise no response will be sent back.
    while response_queue.empty():
        await asyncio.sleep(0.01)

    # Get the response from the response queue.
    response = await response_queue.get()
    return {"status": response["response"]}


@api_bp.get("/whatsapp/wacapi/webhook")
@whatsapp_platform_required
@whatsapp_server_ip_allow_list_required
async def whatsapp_wcapi_verification():
    """Whatsapp Cloud API verification."""
    if (
        request.args.get("hub.mode") == "subscribe"
        and request.args.get("hub.verify_token")
        == current_app.config["ENV"]["whatsapp_webhook_verify_token"]
    ):
        return request.args.get("hub.challenge")
    abort(400)


@api_bp.post("/whatsapp/wacapi/webhook")
@whatsapp_platform_required
@whatsapp_server_ip_allow_list_required
@whatsapp_request_signature_verification_required
async def whatsapp_wcapi_webhook():
    """Respond to Whatsapp Cloud API events."""
    # Get request data.
    data = await request.get_json()

    # Get the IPC queue from the applicaiton object.
    ipc_queue: asyncio.Queue = current_app.whatsapp_ipc_queue

    # Queue allowing IPC queue consumer to send back a response.
    response_queue = asyncio.Queue()

    # Put payload into IPC queue.
    await ipc_queue.put(
        {
            "response_queue": response_queue,
            "command": "whatsapp_wacapi_event",
            "data": data,
        }
    )

    # Ensure other tasks can run,
    # otherwise no response will be sent back.
    while response_queue.empty():
        await asyncio.sleep(0.01)

    # Get the response from the response queue.
    response = await response_queue.get()
    return response


@api_bp.put("/whatsapp/webhook")
@whatsapp_platform_required
async def whatsapp_webhook():
    """Handle IPC calls for the WhatsApp platform."""
    # Get request data.
    data = await request.get_json()

    if "command" not in data.keys() or data["command"] == "":
        abort(400)

    # Get the IPC queue from the applicaiton object.
    ipc_queue: asyncio.Queue = current_app.whatsapp_ipc_queue

    # Queue allowing IPC queue consumer to send back a response.
    response_queue = asyncio.Queue()

    # Put payload into IPC queue.
    await ipc_queue.put(
        {
            "response_queue": response_queue,
            "command": data["command"],
            "data": data,
        }
    )

    # Ensure other tasks can run,
    # otherwise no response will be sent back.
    while response_queue.empty():
        await asyncio.sleep(0.01)

    # Get the response from the response queue.
    response = await response_queue.get()
    return response

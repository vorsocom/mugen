"""Implements API endpoints."""

import asyncio
import json

from quart import abort, current_app, request

from mugen.core import di
from mugen.core.api import api
from mugen_util.decorator import (
    matrix_platform_required,
    whatsapp_platform_required,
    whatsapp_request_signature_verification_required,
    whatsapp_server_ip_allow_list_required,
)


@api.get("/matrix")
@matrix_platform_required(config=di.container.config)
async def matrix_index(ipc_service=di.container.ipc_service):
    """Matrix index endpoint."""

    # Queue allowing IPC queue consumer
    # to send back a response.
    response_queue = asyncio.Queue()

    try:
        await ipc_service.handle_ipc_request(
            "matrix",
            {
                "response_queue": response_queue,
                "command": "matrix_get_status",
            },
        )
    except AttributeError:
        current_app.logger.error("Invalid IPC service.")
        abort(500)

    # Ensure other tasks can run,
    # otherwise no response will be sent back.
    while response_queue.empty():
        await asyncio.sleep(0)

    # Get the response from the response queue.
    response = await response_queue.get()
    return {"status": response["response"]}


@api.put("/matrix/webhook")
@matrix_platform_required(config=di.container.config)
async def matrix_webhook(ipc_service=di.container.ipc_service):
    """Handle IPC calls for the Matrix platform."""
    # Get request data.
    data = await request.get_json()

    try:
        if "command" not in data.keys() or data["command"] == "":
            current_app.logger.error("Invalid JSON data supplied.")
            abort(400)
    except AttributeError:
        current_app.logger.error("JSON data empty.")
        abort(500)

    # Queue allowing IPC queue consumer to send back a response.
    response_queue = asyncio.Queue()

    try:
        await ipc_service.handle_ipc_request(
            "matrix",
            {
                "response_queue": response_queue,
                "command": data["command"],
                "data": data,
            },
        )
    except AttributeError:
        current_app.logger.error("Invalid IPC service.")
        abort(500)

    # Ensure other tasks can run,
    # otherwise no response will be sent back.
    while response_queue.empty():
        await asyncio.sleep(0)

    # Get the response from the response queue.
    response = await response_queue.get()
    return response


@api.get("/whatsapp")
@whatsapp_platform_required(config=di.container.config)
async def whatsapp_index(ipc_service=di.container.ipc_service):
    """Whatsapp index endpoint."""

    # Queue allowing IPC queue consumer to send back a response.
    response_queue = asyncio.Queue()

    try:
        await ipc_service.handle_ipc_request(
            "whatsapp",
            {
                "response_queue": response_queue,
                "command": "whatsapp_get_status",
            },
        )
    except AttributeError:
        current_app.logger.error("Invalid IPC service.")
        abort(500)

    # Ensure other tasks can run,
    # otherwise no response will be sent back.
    while response_queue.empty():
        await asyncio.sleep(0)

    # Get the response from the response queue.
    response = await response_queue.get()
    return {"status": response["response"]}


@api.get("/whatsapp/wacapi/webhook")
@whatsapp_platform_required(config=di.container.config)
@whatsapp_server_ip_allow_list_required(config=di.container.config)
async def whatsapp_wacapi_subscription(config=di.container.config):
    """Whatsapp Cloud API verification."""

    if request.args.get("hub.mode") != "subscribe":
        current_app.logger.error("hub.mode incorrect.")
        abort(400)

    if request.args.get("hub.verify_token") in [None, ""]:
        current_app.logger.error("hub.verify_token not supplied or is empty.")
        abort(400)

    try:
        if (
            request.args.get("hub.verify_token")
            != config.whatsapp.webhook.verification_token
        ):
            current_app.logger.error("Incorrect verification token.")
            abort(400)
    except AttributeError:
        current_app.logger.error("Could not get verification token.")
        abort(500)

    if request.args.get("hub.challenge") in [None, ""]:
        current_app.logger.error("hub.challenge not supplied or is empty.")
        abort(400)

    return request.args.get("hub.challenge")


@api.post("/whatsapp/wacapi/webhook")
@whatsapp_platform_required(config=di.container.config)
@whatsapp_server_ip_allow_list_required(config=di.container.config)
@whatsapp_request_signature_verification_required(config=di.container.config)
async def whatsapp_wacapi_event(ipc_service=di.container.ipc_service):
    """Respond to Whatsapp Cloud API events."""
    # Get request data.
    # get_json was not used to make code more
    # cosistent with signature verification decorator
    # for testing.
    data = await request.get_data()

    try:
        json_data = json.loads(data)
    except json.decoder.JSONDecodeError:
        current_app.logger.error("JSON data could not be decoded.")
        abort(500)

    # Queue allowing IPC queue consumer to send back a response.
    response_queue = asyncio.Queue()

    try:
        await ipc_service.handle_ipc_request(
            "whatsapp",
            {
                "response_queue": response_queue,
                "command": "whatsapp_wacapi_event",
                "data": json_data,
            },
        )
    except AttributeError:
        current_app.logger.error("Invalid IPC service.")
        abort(500)

    # Ensure other tasks can run,
    # otherwise no response will be sent back.
    while response_queue.empty():
        await asyncio.sleep(0)

    # Get the response from the response queue.
    response = await response_queue.get()
    return response


@api.put("/whatsapp/webhook")
@whatsapp_platform_required(config=di.container.config)
async def whatsapp_webhook(ipc_service=di.container.ipc_service):
    """Handle IPC calls for the WhatsApp platform."""
    # Get request data.
    data = await request.get_json()

    try:
        if "command" not in data.keys() or data["command"] == "":
            current_app.logger.error("Invalid JSON data supplied.")
            abort(400)
    except AttributeError:
        current_app.logger.error("JSON data empty.")
        abort(500)

    # Queue allowing IPC queue consumer to send back a response.
    response_queue = asyncio.Queue()

    try:
        await ipc_service.handle_ipc_request(
            "whatsapp",
            {
                "response_queue": response_queue,
                "command": data["command"],
                "data": data,
            },
        )
    except AttributeError:
        current_app.logger.error("Invalid IPC service.")
        abort(500)

    # Ensure other tasks can run,
    # otherwise no response will be sent back.
    while response_queue.empty():
        await asyncio.sleep(0)

    # Get the response from the response queue.
    response = await response_queue.get()
    return response

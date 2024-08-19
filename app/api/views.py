"""Implements API endpoints."""

import asyncio
from quart import current_app, request

from app.api import api_bp


@api_bp.get("/")
async def index():
    """API index endpoint"""
    # Get the IPC queue from the applicaiton object.
    ipc_queue: asyncio.Queue = current_app.ipc_queue

    # Queue allowing IPC queue consumer to send back a response.
    response_queue = asyncio.Queue()

    # Put payload into IPC queue.
    await ipc_queue.put({"response_queue": response_queue, "command": "get_status"})

    # Ensure other tasks can run,
    # otherwise no response will be sent back.
    while response_queue.empty():
        await asyncio.sleep(0)

    # Get the response from the response queue.
    response = await response_queue.get()
    return {"status": response["response"]}


@api_bp.put("/cron")
async def cron():
    """Perform a cron task."""
    # Get request data.
    data = await request.get_json()

    # Get the IPC queue from the applicaiton object.
    ipc_queue: asyncio.Queue = current_app.ipc_queue

    # Queue allowing IPC queue consumer to send back a response.
    response_queue = asyncio.Queue()

    # Put payload into IPC queue.
    await ipc_queue.put(
        {
            "response_queue": response_queue,
            "command": "cron",
            "data": data,
        }
    )

    # Ensure other tasks can run,
    # otherwise no response will be sent back.
    while response_queue.empty():
        await asyncio.sleep(0)

    # Get the response from the response queue.
    response = await response_queue.get()
    return response

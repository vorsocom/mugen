"""Application entry point."""

__author__ = "Vorso Computing, Inc."

__copyright__ = "Copyright © 2024, Vorso Computing, Inc."

__email__ = "brightideas@vorsocomputing.com"

__version__ = "0.10.1"

import asyncio
import os

from app import create_app
from app.nio.assistant import run_assistant

from config import APP_PREFIX, BASEDIR

# Queue to allow communication between Quart and matrix-nio.
ipc_queue = asyncio.Queue()

# Create Quart app.
app = create_app(os.getenv(f"{APP_PREFIX}_CONFIG", "default"), ipc_queue)


@app.before_serving
async def startup():
    """Initialise matrix-nio using the Quart event loop."""
    loop = asyncio.get_event_loop()
    loop.create_task(run_assistant(BASEDIR, app.config.get("LOG_LEVEL"), ipc_queue))

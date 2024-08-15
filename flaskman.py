"""Application entry point."""

import asyncio
import os
import threading

from app import create_app
from app.nio.assistant import run_assistant

from config import APP_PREFIX, BASEDIR

# Queue to allow communication between Flask and matrix-nio.
ipc_queue = asyncio.Queue()

# Create Flask app.
app = create_app(os.getenv(f"{APP_PREFIX}_CONFIG", "default"), ipc_queue)

# Run matrix-nio assistant.
threading.Thread(
    target=run_assistant, args=(BASEDIR, app.config.get("LOG_LEVEL"), ipc_queue)
).start()

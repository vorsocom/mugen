"""Application entry point."""

import os
import threading
from queue import Queue

from app import create_app
from app.nio.assistant import run_assistant

from config import APP_PREFIX, BASEDIR


app = create_app(os.getenv(f"{APP_PREFIX}_CONFIG", "default"))
ipc_queue = Queue()

# run_assistant(BASEDIR, ipc_queue)
threading.Thread(target=run_assistant, args=(BASEDIR, ipc_queue)).start()

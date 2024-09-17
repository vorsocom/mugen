"""Application entry point."""

__author__ = "Vorso Computing, Inc."

__copyright__ = "Copyright © 2024, Vorso Computing, Inc."

__email__ = "brightideas@vorsocomputing.com"

__version__ = "0.26.1"

import asyncio

from mugen import create_quart_app, run_assistants

# Create Quart mugen.
mugen = create_quart_app()


@mugen.before_serving
async def startup():
    """Initialise matrix-nio using the Quart event loop."""
    loop = asyncio.get_event_loop()
    loop.create_task(run_assistants())

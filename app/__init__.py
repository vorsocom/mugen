"""Flask application package."""

__all__ = ["create_app"]

import asyncio
import sys

from flask import Flask, g

from config import AppConfig

from .api import api_bp

app = Flask(__name__)


def create_app(config_name, ipc_queue: asyncio.Queue):
    """Application factory."""
    # Check for valid configuration name.
    if config_name not in ("default", "development", "testing", "production"):
        print("Invalid configuration name.")
        sys.exit(1)

    app.logger.warning("Creating app with %s configuration.", config_name)

    # Create application configuration object.
    app.config.from_object(AppConfig[config_name])

    # Initialize application.
    AppConfig[config_name].init_app(app)

    # Register blueprints.
    app.register_blueprint(api_bp, url_prefix="/api")

    @app.after_request
    def call_after_request_callbacks(response):
        """Ensure all registered after-request-callbacks are called."""
        for callback in getattr(g, "after_request_callbacks", ()):
            callback(response)
        return response

    # Ensure that API endpoints can access the ipc_queue
    # through current_app.ipc_queue
    app.ipc_queue = ipc_queue

    # Return the built application object.
    return app

"""Implements the API."""

__all__ = ["api"]

from quart import Blueprint

api = Blueprint("api", __name__)

# Register endpoint handlers on blueprint import.
from . import endpoint as _endpoint  # noqa: E402,F401  pylint: disable=wrong-import-position,unused-import

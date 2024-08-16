"""Implements the API."""

__all__ = ["api_bp"]

from quart import Blueprint

api_bp = Blueprint("api", __name__)

# pylint: disable=wrong-import-position
from . import views

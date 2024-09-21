"""Implements the API."""

__all__ = ["api"]

from quart import Blueprint

api = Blueprint("api", __name__)

# pylint: disable=wrong-import-position
from . import views

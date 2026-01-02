"""Implements the API."""

__all__ = ["api"]

from quart import Blueprint

api = Blueprint("api", __name__)

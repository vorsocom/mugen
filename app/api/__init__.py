"""Implements the API."""

__all__ = ["api"]

from flask import Blueprint

api = Blueprint("api", __name__)

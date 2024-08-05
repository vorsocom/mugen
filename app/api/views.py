"""Implements API endpoints."""

from app.api import api

@api.route("/")
def index():
    """API index endpoint"""

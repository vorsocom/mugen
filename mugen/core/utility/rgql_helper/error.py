"""Provide error types for RGQL handling."""


class RGQLExpandError(Exception):
    """An error type raised during RGQL expansions."""

    status_code: int

    message: str

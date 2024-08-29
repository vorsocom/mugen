"""Provides a response class for CancelScheduledMeetingInteractor."""

# pylint: disable=too-few-public-methods

__all__ = ["CancelScheduledMeetingResponse"]

from app.core.contract.response import IResponse


class CancelScheduledMeetingResponse(IResponse):
    """An CancelScheduledMeetingInteractor response."""

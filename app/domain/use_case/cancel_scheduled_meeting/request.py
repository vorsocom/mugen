"""Provides a request class for CancelScheduledMeetingInteractor."""

# pylint: disable=too-few-public-methods

__all__ = ["CancelScheduledMeetingRequest"]

from app.contract.request import IRequest
from app.domain.entity.meeting import Meeting


class CancelScheduledMeetingRequest(IRequest["CancelScheduledMeetingRequest"]):
    """An CancelScheduledMeetingInteractor request."""

    meeting: Meeting

    initiator: str

    def __init__(self, meeting: Meeting, initiator: str) -> None:
        self.meeting = meeting
        self.initiator = initiator

"""Provides a request class for UpdateScheduledMeetingInteractor."""

# pylint: disable=too-few-public-methods

__all__ = ["UpdateScheduledMeetingRequest"]

from app.contract.request import IRequest
from app.domain.entity.meeting import Meeting


class UpdateScheduledMeetingRequest(IRequest["UpdateScheduledMeetingRequest"]):
    """An UpdateScheduledMeetingInteractor request."""

    meeting: Meeting

    change_topic: bool

    def __init__(self, meeting: Meeting, change_topic: bool = False) -> None:
        self.meeting = meeting
        self.change_topic = change_topic

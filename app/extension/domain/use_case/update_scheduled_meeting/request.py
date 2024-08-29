"""Provides a request class for UpdateScheduledMeetingInteractor."""

__all__ = ["UpdateScheduledMeetingRequest"]

from app.core.contract.request import IRequest
from app.extension.domain.entity.meeting import Meeting


# pylint: disable=too-few-public-methods
class UpdateScheduledMeetingRequest(IRequest["UpdateScheduledMeetingRequest"]):
    """An UpdateScheduledMeetingInteractor request."""

    meeting: Meeting

    change_topic: bool

    def __init__(self, meeting: Meeting, change_topic: bool = False) -> None:
        self.meeting = meeting
        self.change_topic = change_topic

"""Provides a response class for UpdateScheduledMeetingInteractor."""

__all__ = ["UpdateScheduledMeetingResponse"]

from app.core.contract.response import IResponse
from app.extension.domain.entity.meeting import Meeting


# pylint: disable=too-few-public-methods
class UpdateScheduledMeetingResponse(IResponse):
    """An UpdateScheduledMeetingInteractor response."""

    meeting: Meeting | None

    def __init__(
        self,
        success: bool,
        messages: list[str] | None = None,
        meeting: Meeting | None = None,
    ) -> None:
        super().__init__(success, messages)
        self.meeting = meeting

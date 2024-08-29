"""Provides a response class for ScheduleMeetingInteractor."""

# pylint: disable=too-few-public-methods

__all__ = ["ScheduleMeetingResponse"]

from app.core.contract.response import IResponse
from app.extension.domain.entity.meeting import Meeting


class ScheduleMeetingResponse(IResponse):
    """A ScheduleMeetingInteractor response."""

    meeting: Meeting | None

    def __init__(
        self,
        success: bool,
        messages: list[str] | None = None,
        meeting: Meeting | None = None,
    ) -> None:
        super().__init__(success, messages)
        self.meeting = meeting

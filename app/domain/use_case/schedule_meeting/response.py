"""Provides a response class for ScheduleMeetingInteractor."""

# pylint: disable=too-few-public-methods

__all__ = ["ScheduleMeetingResponse"]

from typing import Optional

from app.contract.response import IResponse
from app.domain.entity.meeting import Meeting


class ScheduleMeetingResponse(IResponse):
    """A ScheduleMeetingInteractor response."""

    meeting: Optional[Meeting]

    def __init__(
        self,
        success: bool,
        messages: Optional[list[str]] = None,
        meeting: Optional[Meeting] = None,
    ) -> None:
        super().__init__(success, messages)
        self.meeting = meeting

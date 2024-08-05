"""Provides a request class for ScheduleMeetingInteractor."""

__all__ = ["ScheduleMeetingRequest"]

from typing import Optional

from app.contract.request import IRequest
from app.domain.entity.meeting import CreateMeetingDTO


class ScheduleMeetingRequest(IRequest["ScheduleMeetingRequest"]):
    """A ScheduleMeetingInteractor request."""

    init_data = CreateMeetingDTO

    location: Optional[str]

    expires_after: Optional[int]

    def __init__(
        self,
        init_data: CreateMeetingDTO,
        location: Optional[str] = None,
        expires_after: Optional[int] = None,
    ) -> None:
        self.init_data = init_data
        self.location = location
        self.expires_after = expires_after

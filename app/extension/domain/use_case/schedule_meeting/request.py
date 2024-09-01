"""Provides a request class for ScheduleMeetingInteractor."""

__all__ = ["ScheduleMeetingRequest"]

from app.core.contract.request import IRequest
from app.extension.domain.entity.meeting import CreateMeetingDTO


class ScheduleMeetingRequest(IRequest["ScheduleMeetingRequest"]):
    """A ScheduleMeetingInteractor request."""

    init_data = CreateMeetingDTO

    location: str | None

    expires_after: int | None

    def __init__(
        self,
        init_data: CreateMeetingDTO,
        location: str | None = None,
        expires_after: int | None = None,
    ) -> None:
        self.init_data = init_data
        self.location = location
        self.expires_after = expires_after

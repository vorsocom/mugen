"""Provides the Meeting entity."""

__all__ = ["Meeting"]

from collections import namedtuple
from typing import Optional
from datetime import datetime


CreateMeetingDTO = namedtuple(
    "CreateMeetingDTO", ["type", "topic", "date", "time", "attendees", "scheduler"]
)


class Meeting:
    """Implements a meeting."""

    init: CreateMeetingDTO

    room_id: Optional[str]

    location: Optional[str]

    expires_after: Optional[int]

    def __init__(
        self,
        init: CreateMeetingDTO,
        expires_after: Optional[int] = None,
        location: Optional[str] = None,
        room_id: Optional[str] = None,
    ) -> None:
        self.init = init
        self.expires_after = expires_after
        self.location = location
        self.room_id = room_id

    def get_datetime(self) -> datetime:
        """Gets the meeting date and time as a datetime object."""
        return datetime.strptime(
            f"{self.init.date} {self.init.time}", "%Y-%m-%d %H:%M:%S"
        )

    def is_expired(self) -> bool:
        """Indicates if the meeting has expired.
        i.e. the "expires_after" time has elapsed.
        """
        if self.expires_after is None:
            return False

        diff = datetime.now() - self.get_datetime()
        return diff.total_seconds() > self.expires_after

    def is_virtual(self) -> bool:
        """Indicates if the meeting is virtual."""
        return self.init.type == "virtual"

"""Provides an abstract base class for user services."""

__all__ = ["IUserService"]

from abc import ABC, abstractmethod


class IUserService(ABC):
    """An ABC for user services."""

    @abstractmethod
    def add_known_user(self, user_id: str, displayname: str, room_id: str) -> None:
        """Add a user to the list of known users."""

    @abstractmethod
    def get_known_users_list(self) -> dict:
        """Get the list of known users."""

    @abstractmethod
    def get_user_display_name(self, user_id: str) -> str:
        """Get a user's display name from the list of known users."""

    @abstractmethod
    def save_known_users_list(self, known_users: dict) -> None:
        """Save a list of known users."""

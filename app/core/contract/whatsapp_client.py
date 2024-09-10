"""Provides an abstract base class for WhatsApp clients."""

__all__ = ["IWhatsAppClient"]

from abc import ABC, abstractmethod


class IWhatsAppClient(ABC):
    """An ABC for WhatsApp clients."""

    @abstractmethod
    async def listen_forever(self) -> None:
        """Listen for events from the WhatsApp Cloud API."""

    @abstractmethod
    async def delete_media(self, media_id: str) -> str | None:
        """Delete a media file from WhatsApp."""

    @abstractmethod
    async def download_media(self, media_url: str) -> str | None:
        """Download a media file from WhatsApp."""

    @abstractmethod
    async def retrieve_media_url(self, media_id: str) -> str | None:
        """Retrieve a media file URL from WhatsApp."""

    @abstractmethod
    async def send_audio_message(
        self,
        audio: dict,
        recipient: str,
        reply_to: str,
    ) -> str | None:
        """Send an Audio message to a WhatsApp user."""

    @abstractmethod
    async def send_contacts_message(
        self,
        contacts: dict,
        recipient: str,
        reply_to: str,
    ) -> str | None:
        """Send a Contacts message to a WhatsApp user."""

    @abstractmethod
    async def send_document_message(
        self,
        document: dict,
        recipient: str,
        reply_to: str,
    ) -> str | None:
        """Send a Document message to a WhatsApp user."""

    @abstractmethod
    async def send_image_message(
        self,
        image: dict,
        recipient: str,
        reply_to: str,
    ) -> str | None:
        """Send an Image message to a WhatsApp user."""

    @abstractmethod
    async def send_interactive_message(
        self,
        interactive: dict,
        recipient: str,
        reply_to: str,
    ) -> str | None:
        """Send an Interactive message to a WhatsApp user.

        This applies to:
        1. Addresses.
        2. Interactive CTA URL Button.
        3. Interactive Flow.
        4. Interactive List.
        5. Interactive Location Request.
        6. Interactive Reply Buttons.
        """

    @abstractmethod
    async def send_location_message(
        self,
        location: dict,
        recipient: str,
        reply_to: str,
    ) -> str | None:
        """Send a Location message to a WhatsApp user."""

    @abstractmethod
    async def send_reaction_message(self, reaction: dict, recipient: str) -> str | None:
        """Send a Reaction message to a WhatsApp user."""

    @abstractmethod
    async def send_sticker_message(
        self,
        sticker: dict,
        recipient: str,
        reply_to: str,
    ) -> str | None:
        """Send a Sticker message to a WhatsApp user."""

    @abstractmethod
    async def send_template_message(
        self,
        template: dict,
        recipient: str,
        reply_to: str,
    ) -> str | None:
        """Send a Template message to a WhatsApp user.

        This applies to:
        1. Text-based.
        2. Media-based.
        3. Interactive.
        4. Location-based.
        5. Authentication.
        6. Multi-Product Message.
        """

    @abstractmethod
    async def send_text_message(
        self,
        message: str,
        recipient: str,
        reply_to: str,
    ) -> str | None:
        """Send a Text message to a WhatsApp user."""

    @abstractmethod
    async def send_video_message(
        self,
        video: dict,
        recipient: str,
        reply_to: str,
    ) -> str | None:
        """Send a Video message to a WhatsApp user."""

    @abstractmethod
    async def upload_media(
        self,
        file_name: str,
        file_path: str,
        file_type: str,
    ) -> str | None:
        """Upload a media file to WhatsApp."""

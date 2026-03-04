"""Telegram Bot API plugin models."""

__all__ = [
    "TelegramBotAPIEventDedup",
    "TelegramBotAPIEventDeadLetter",
]

from mugen.core.plugin.telegram.botapi.model.event_dedup import (
    TelegramBotAPIEventDedup,
)
from mugen.core.plugin.telegram.botapi.model.event_dead_letter import (
    TelegramBotAPIEventDeadLetter,
)

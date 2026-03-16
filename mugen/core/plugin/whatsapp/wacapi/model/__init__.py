"""WACAPI plugin models."""

__all__ = [
    "WhatsAppWACAPIEventDedup",
    "WhatsAppWACAPIEventDeadLetter",
]

from mugen.core.plugin.whatsapp.wacapi.model.event_dedup import (
    WhatsAppWACAPIEventDedup,
)
from mugen.core.plugin.whatsapp.wacapi.model.event_dead_letter import (
    WhatsAppWACAPIEventDeadLetter,
)

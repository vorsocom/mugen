"""Signal REST API plugin models."""

__all__ = [
    "SignalRestAPIEventDedup",
    "SignalRestAPIEventDeadLetter",
]

from mugen.core.plugin.signal.restapi.model.event_dedup import (
    SignalRestAPIEventDedup,
)
from mugen.core.plugin.signal.restapi.model.event_dead_letter import (
    SignalRestAPIEventDeadLetter,
)

"""Structured memory write primitives."""

from __future__ import annotations

__all__ = ["MemoryWrite", "MemoryWriteType"]

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from mugen.core.contract.context.artifact import ContextProvenance


class MemoryWriteType(str, Enum):
    """Stable write classes for long-term memory persistence."""

    FACT = "fact"
    PREFERENCE = "preference"
    COMMITMENT = "commitment"
    RELATION = "relation"
    EPISODE = "episode"
    SUMMARY = "summary"
    TOMBSTONE = "tombstone"


@dataclass(frozen=True, slots=True)
class MemoryWrite:
    """One structured memory write intent derived from a completed turn."""

    write_type: MemoryWriteType
    content: str | dict[str, Any]
    provenance: ContextProvenance
    scope_partition: dict[str, str] = field(default_factory=dict)
    key: str | None = None
    subject: str | None = None
    confidence: float | None = None
    ttl_seconds: int | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

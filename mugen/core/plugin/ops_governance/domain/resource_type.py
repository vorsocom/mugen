"""Shared resource-type canonicalization for ops_governance services."""

__all__ = [
    "canonicalize_resource_type",
]

_CANONICAL_RESOURCE_TYPE_BY_TOKEN: dict[str, str] = {
    "audit": "audit_event",
    "auditevent": "audit_event",
    "audit_event": "audit_event",
    "evidence": "evidence_blob",
    "evidenceblob": "evidence_blob",
    "evidence_blob": "evidence_blob",
}


def canonicalize_resource_type(value: str | None) -> str:
    """Normalize known aliases into canonical resource type tokens."""
    token = str(value or "").strip().lower().replace("-", "_")
    canonical = _CANONICAL_RESOURCE_TYPE_BY_TOKEN.get(token)
    if canonical is None:
        raise ValueError(f"Unsupported resource type: {value!r}.")
    return canonical

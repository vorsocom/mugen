"""Shared provider-neutral helpers for knowledge gateway adapters."""

from __future__ import annotations

__all__ = [
    "apply_query_scope",
    "document_metadata",
    "resolve_hugging_face_token",
    "resolve_encoder_revision",
    "selector_metadata",
]

from collections.abc import Mapping
from pathlib import Path
import re
from typing import Any

from mugen.core.contract.gateway.knowledge import (
    KnowledgeDeleteSelector,
    KnowledgeIndexDocument,
    KnowledgeSearchHit,
    KnowledgeSearchQuery,
)

_SCOPE_FIELDS = (
    "channel",
    "locale",
    "category",
    "service_route_key",
    "client_profile_key",
    "service_profile_id",
)

# Published by sentence-transformers; includes model.safetensors. Updating this
# pin requires reviewing the model repository and its serialization format.
DEFAULT_ENCODER_REVISION = "e8c3b32edf5434bc2275fc9bab85f82640a19130"


def resolve_encoder_revision(model_name: str, encoder_config: object) -> str:
    """Require an immutable, operator-reviewed model revision before loading."""
    if (
        re.fullmatch(
            r"(?:[A-Za-z0-9][A-Za-z0-9_.-]*/)?[A-Za-z0-9][A-Za-z0-9_.-]*", model_name
        )
        is None
        or Path(model_name).exists()
    ):
        raise RuntimeError(
            "Invalid configuration: encoder.model must identify a Hugging Face "
            "repository, not a local path (which bypasses revision pinning)."
        )
    revision = getattr(encoder_config, "revision", None)
    if revision is None and model_name in (
        "all-mpnet-base-v2",
        "sentence-transformers/all-mpnet-base-v2",
    ):
        return DEFAULT_ENCODER_REVISION
    if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise RuntimeError(
            "Invalid configuration: encoder.revision must be a full, reviewed "
            "Hugging Face commit SHA for encoder.model."
        )
    return revision


def document_metadata(document: KnowledgeIndexDocument) -> dict[str, Any]:
    """Return provider-safe metadata, omitting null values when required later."""
    return document.metadata()


def selector_metadata(selector: KnowledgeDeleteSelector) -> dict[str, str]:
    """Return the required tenant and optional pack/version deletion constraints."""
    result = {"tenant_id": str(selector.tenant_id)}
    if selector.knowledge_pack_id is not None:
        result["knowledge_pack_id"] = str(selector.knowledge_pack_id)
    if selector.knowledge_pack_version_id is not None:
        result["knowledge_pack_version_id"] = str(selector.knowledge_pack_version_id)
    return result


def resolve_hugging_face_token(hf_config: object) -> str | None:
    """Return the normalized optional Hugging Face authentication token."""
    raw_token = getattr(hf_config, "token", None)
    if raw_token is None:
        return None
    if not isinstance(raw_token, str):
        raise RuntimeError(
            "Invalid configuration: transformers.hf.token must be a string."
        )
    normalized = raw_token.strip()
    return normalized or None


def _scope_matches(hit: KnowledgeSearchHit, query: KnowledgeSearchQuery) -> bool:
    if (
        query.knowledge_pack_id is not None
        and hit.knowledge_pack_id != query.knowledge_pack_id
    ):
        return False
    if (
        query.knowledge_pack_version_id is not None
        and hit.knowledge_pack_version_id != query.knowledge_pack_version_id
    ):
        return False
    for field_name in _SCOPE_FIELDS:
        requested = getattr(query, field_name)
        stored = getattr(hit, field_name)
        if field_name == "service_profile_id":
            if requested is None:
                if stored is not None:
                    return False
            elif stored not in (None, requested):
                return False
            continue
        if requested is not None and stored not in (None, requested):
            return False
    return True


def apply_query_scope(
    items: list[KnowledgeSearchHit | Mapping[str, Any]],
    query: KnowledgeSearchQuery,
) -> list[KnowledgeSearchHit]:
    """Apply wildcard semantics, exact-scope precedence, and the candidate limit."""
    hits = [
        (
            item
            if isinstance(item, KnowledgeSearchHit)
            else KnowledgeSearchHit.from_mapping(item)
        )
        for item in items
    ]
    eligible = [hit for hit in hits if _scope_matches(hit, query)]
    eligible.sort(
        key=lambda hit: (
            -hit.scope_specificity(query),
            -(hit.similarity if hit.similarity is not None else float("-inf")),
            hit.distance if hit.distance is not None else float("inf"),
            str(hit.knowledge_entry_revision_id),
            str(hit.knowledge_scope_id or ""),
        )
    )
    return eligible[: query.candidate_limit]

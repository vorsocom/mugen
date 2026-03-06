"""Shared context-runtime helpers for scope identity and cache keys."""

from __future__ import annotations

__all__ = [
    "messages_fingerprint",
    "prefix_cache_prefix",
    "prefix_cache_key",
    "retrieval_cache_key",
    "retrieval_cache_prefix",
    "scope_identity",
    "scope_key",
    "scope_partition",
    "tenant_cache_key",
    "working_set_cache_key",
    "working_set_cache_prefix",
]

import hashlib
import json
from typing import Any

from mugen.core.contract.context import ContextScope, ContextTurnRequest
from mugen.core.contract.gateway.completion import CompletionMessage


def _hash_payload(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def scope_identity(scope: ContextScope) -> dict[str, Any]:
    return {
        "tenant_id": scope.tenant_id,
        "platform": scope.platform,
        "channel_id": scope.channel_id,
        "room_id": scope.room_id,
        "sender_id": scope.sender_id,
        "conversation_id": scope.conversation_id,
        "case_id": scope.case_id,
        "workflow_id": scope.workflow_id,
    }


def scope_key(scope: ContextScope) -> str:
    return _hash_payload(scope_identity(scope))


def scope_partition(scope: ContextScope) -> dict[str, str]:
    partition: dict[str, str] = {}
    for key in (
        "platform",
        "channel_id",
        "room_id",
        "sender_id",
        "conversation_id",
        "case_id",
        "workflow_id",
    ):
        value = getattr(scope, key)
        if isinstance(value, str) and value != "":
            partition[key] = value
    return partition


def tenant_cache_key(tenant_id: str, suffix: str) -> str:
    return f"tenant:{tenant_id}:{suffix}"


def working_set_cache_key(scope: ContextScope) -> str:
    return tenant_cache_key(scope.tenant_id, f"working_set:{scope_key(scope)}")


def working_set_cache_prefix(scope: ContextScope) -> str:
    return tenant_cache_key(scope.tenant_id, f"working_set:{scope_key(scope)}")


def retrieval_cache_key(request: ContextTurnRequest) -> str:
    request_hash = _hash_payload(
        {
            "scope": scope_identity(request.scope),
            "message": request.user_message,
            "message_context": request.message_context,
            "attachment_context": request.attachment_context,
        }
    )
    return tenant_cache_key(
        request.scope.tenant_id,
        f"retrieval:{scope_key(request.scope)}:{request_hash}",
    )


def retrieval_cache_prefix(scope: ContextScope) -> str:
    return tenant_cache_key(scope.tenant_id, f"retrieval:{scope_key(scope)}")


def prefix_cache_key(scope: ContextScope, prefix_fingerprint: str) -> str:
    return tenant_cache_key(
        scope.tenant_id,
        f"prefix_fingerprint:{scope_key(scope)}:{prefix_fingerprint}",
    )


def prefix_cache_prefix(scope: ContextScope) -> str:
    return tenant_cache_key(scope.tenant_id, f"prefix_fingerprint:{scope_key(scope)}")


def messages_fingerprint(messages: list[CompletionMessage]) -> str:
    return _hash_payload([message.to_dict() for message in messages])

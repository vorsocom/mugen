"""Default contributors for the context_engine plugin."""

from __future__ import annotations

__all__ = [
    "AuditContributor",
    "ChannelOrchestrationContributor",
    "KnowledgePackContributor",
    "MemoryContributor",
    "PersonaPolicyContributor",
    "RecentTurnContributor",
    "StateContributor",
    "OpsCaseContributor",
]

import json
import uuid
from typing import Any

from mugen.core.constants import GLOBAL_TENANT_ID
from mugen.core.contract.context import (
    ContextArtifact,
    ContextCandidate,
    ContextPolicy,
    ContextProvenance,
    ContextState,
    ContextSourceRef,
    ContextTurnRequest,
    IContextContributor,
)
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup, OrderBy
from mugen.core.plugin.audit.service.audit_biz_trace_event import (
    AuditBizTraceEventService,
)
from mugen.core.plugin.channel_orchestration.service.conversation_state import (
    ConversationStateService,
)
from mugen.core.plugin.channel_orchestration.service.work_item import WorkItemService
from mugen.core.plugin.context_engine.service.runtime import (
    ContextEventLogService,
    ContextMemoryRecordService,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_scope import (
    KnowledgeScopeService,
)
from mugen.core.plugin.ops_case.service.case import CaseService
from mugen.core.plugin.ops_case.service.case_event import CaseEventService
from mugen.core.utility.context_runtime import scope_key


def _estimate_token_cost(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return max(len(value) // 4, 1)
    try:
        return max(len(json.dumps(value, default=str)) // 4, 1)
    except (TypeError, ValueError):
        return 32


def _excerpt_text(value: str, *, limit: int = 1000) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _parse_tenant_uuid(scope) -> uuid.UUID:
    return uuid.UUID(str(scope.tenant_id))


def _memory_partition_matches(partition: dict[str, Any] | None, scope) -> bool:
    if not isinstance(partition, dict):
        return True
    for key in (
        "channel_id",
        "room_id",
        "sender_id",
        "conversation_id",
        "case_id",
        "workflow_id",
    ):
        value = partition.get(key)
        if value in (None, ""):
            continue
        if getattr(scope, key) != value:
            return False
    return True


def _memory_source_key(row: Any) -> str | None:
    memory_key = getattr(row, "memory_key", None)
    if isinstance(memory_key, str) and memory_key.strip() != "":
        return memory_key.strip()
    row_id = getattr(row, "id", None)
    if row_id is None:
        return None
    return str(row_id)


def _normalize_revision_source_key(revision: Any) -> str | None:
    for attribute in (
        "scope_key",
        "knowledge_scope_key",
        "knowledge_key",
        "source_key",
    ):
        value = getattr(revision, attribute, None)
        if isinstance(value, str) and value.strip() != "":
            return value.strip()
    revision_id = getattr(revision, "id", None)
    if revision_id is None:
        return None
    return str(revision_id)


def _source_ref(
    *,
    kind: str,
    source_key: str | None = None,
    source_id: str | None = None,
    canonical_locator: str | None = None,
    segment_id: str | None = None,
    locale: str | None = None,
    category: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ContextSourceRef:
    return ContextSourceRef(
        kind=kind,
        source_key=source_key,
        source_id=source_id,
        canonical_locator=canonical_locator,
        segment_id=segment_id,
        locale=locale,
        category=category,
        metadata=dict(metadata or {}),
    )


def _provenance(
    *,
    contributor: str,
    source_kind: str,
    tenant_id: str,
    trace_id: str | None,
    source_key: str | None = None,
    source_id: str | None = None,
    canonical_locator: str | None = None,
    segment_id: str | None = None,
    locale: str | None = None,
    category: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ContextProvenance:
    return ContextProvenance(
        contributor=contributor,
        source_kind=source_kind,
        source_id=source_id,
        source=_source_ref(
            kind=source_kind,
            source_key=source_key,
            source_id=source_id,
            canonical_locator=canonical_locator,
            segment_id=segment_id,
            locale=locale,
            category=category,
            metadata=metadata,
        ),
        tenant_id=tenant_id,
        trace_id=trace_id,
        metadata=dict(metadata or {}),
    )


class PersonaPolicyContributor(IContextContributor):
    """Compile assistant persona plus resolved policy into the first system lane."""

    name = "persona_policy"

    async def collect(
        self,
        request: ContextTurnRequest,
        *,
        policy: ContextPolicy,
        state: ContextState | None,
    ) -> list[ContextCandidate]:
        _ = state
        persona = policy.metadata.get("persona")
        content = {
            "persona": persona,
            "policy_key": policy.policy_key,
            "budget": {
                "max_total_tokens": policy.budget.max_total_tokens,
                "max_selected_artifacts": policy.budget.max_selected_artifacts,
                "max_recent_turns": policy.budget.max_recent_turns,
            },
            "redaction": {
                "redact_sensitive": policy.redaction.redact_sensitive,
                "blocked_sensitivity_labels": list(
                    policy.redaction.blocked_sensitivity_labels
                ),
            },
            "tenant_resolution": request.ingress_metadata.get("tenant_resolution"),
        }
        artifact = ContextArtifact(
            artifact_id=f"persona-policy:{policy.policy_key or 'default'}",
            lane="system_persona_policy",
            kind="persona_policy",
            render_class="system_persona_policy_items",
            title="Persona and policy",
            summary="Resolved assistant persona and context policy.",
            content=content,
            provenance=_provenance(
                contributor=self.name,
                source_kind="context_policy",
                source_key=policy.policy_key or "default",
                source_id=policy.policy_key or "default",
                canonical_locator=f"context-policy:{policy.policy_key or 'default'}",
                tenant_id=request.scope.tenant_id,
                trace_id=request.trace_id,
            ),
            trust=1.0,
            freshness=1.0,
            estimated_token_cost=_estimate_token_cost(content),
        )
        return [
            ContextCandidate(artifact=artifact, contributor=self.name, priority=100)
        ]


class StateContributor(IContextContributor):
    """Emit the bounded control state lane."""

    name = "state"

    async def collect(
        self,
        request: ContextTurnRequest,
        *,
        policy: ContextPolicy,
        state: ContextState | None,
    ) -> list[ContextCandidate]:
        _ = request
        _ = policy
        if state is None:
            return []
        artifact = ContextArtifact(
            artifact_id="bounded-state",
            lane="bounded_control_state",
            kind="state_snapshot",
            render_class="bounded_control_state_items",
            title="Bounded control state",
            summary=state.summary,
            content={
                "current_objective": state.current_objective,
                "entities": state.entities,
                "constraints": state.constraints,
                "unresolved_slots": state.unresolved_slots,
                "commitments": state.commitments,
                "safety_flags": state.safety_flags,
                "routing": state.routing,
                "summary": state.summary,
            },
            provenance=_provenance(
                contributor=self.name,
                source_kind="state_snapshot",
                source_key=scope_key(request.scope),
                canonical_locator=f"state-snapshot:{scope_key(request.scope)}",
                tenant_id=request.scope.tenant_id,
                trace_id=request.trace_id,
            ),
            trust=1.0,
            freshness=1.0,
            estimated_token_cost=_estimate_token_cost(state.summary or state.entities),
        )
        return [ContextCandidate(artifact=artifact, contributor=self.name, priority=90)]


class RecentTurnContributor(IContextContributor):
    """Emit a bounded recent interaction window."""

    name = "recent_turns"

    def __init__(self, *, event_log_service: ContextEventLogService) -> None:
        self._event_log_service = event_log_service

    async def collect(
        self,
        request: ContextTurnRequest,
        *,
        policy: ContextPolicy,
        state: ContextState | None,
    ) -> list[ContextCandidate]:
        _ = state
        tenant_id = _parse_tenant_uuid(request.scope)
        scope_key_value = scope_key(request.scope)
        rows = await self._event_log_service.list(
            filter_groups=[
                FilterGroup(
                    where={"tenant_id": tenant_id, "scope_key": scope_key_value}
                ),
            ],
            order_by=[OrderBy("occurred_at", descending=True)],
            limit=policy.budget.max_recent_messages,
        )
        candidates: list[ContextCandidate] = []
        for row in reversed(list(rows)):
            artifact = ContextArtifact(
                artifact_id=f"recent-turn:{row.id}",
                lane="recent_turn",
                kind="recent_turn",
                render_class="recent_turn_messages",
                title=None,
                summary=None,
                content={"role": row.role, "content": row.content},
                provenance=_provenance(
                    contributor=self.name,
                    source_kind="event_log",
                    source_key=scope_key_value,
                    source_id=None if row.id is None else str(row.id),
                    canonical_locator=(
                        None
                        if row.id is None
                        else f"context-event-log:{scope_key_value}:{row.id}"
                    ),
                    segment_id=None if row.id is None else str(row.id),
                    tenant_id=request.scope.tenant_id,
                    trace_id=row.trace_id,
                ),
                trust=1.0,
                freshness=1.0,
                estimated_token_cost=_estimate_token_cost(row.content),
            )
            candidates.append(
                ContextCandidate(artifact=artifact, contributor=self.name, priority=20)
            )
        return candidates


class KnowledgePackContributor(IContextContributor):
    """Retrieve tenant-scoped published knowledge spans."""

    name = "knowledge_pack"

    def __init__(self, *, knowledge_scope_service: KnowledgeScopeService) -> None:
        self._knowledge_scope_service = knowledge_scope_service

    async def collect(
        self,
        request: ContextTurnRequest,
        *,
        policy: ContextPolicy,
        state: ContextState | None,
    ) -> list[ContextCandidate]:
        _ = policy
        _ = state
        tenant_id = _parse_tenant_uuid(request.scope)
        locale = request.ingress_metadata.get("locale")
        category = request.ingress_metadata.get("category")
        revisions = await self._knowledge_scope_service.list_published_revisions(
            tenant_id=tenant_id,
            channel=request.scope.channel_id or request.scope.platform,
            locale=locale if isinstance(locale, str) else None,
            category=category if isinstance(category, str) else None,
        )
        candidates: list[ContextCandidate] = []
        for revision in revisions:
            excerpt = None
            if isinstance(revision.body, str) and revision.body.strip():
                excerpt = _excerpt_text(revision.body)
            elif revision.body_json:
                excerpt = _excerpt_text(json.dumps(revision.body_json, sort_keys=True))
            if excerpt is None:
                continue
            content = {
                "excerpt": excerpt,
                "channel": revision.channel,
                "locale": revision.locale,
                "category": revision.category,
                "published_at": (
                    None
                    if revision.published_at is None
                    else revision.published_at.isoformat()
                ),
            }
            artifact = ContextArtifact(
                artifact_id=f"knowledge:{revision.id}",
                lane="evidence",
                kind="knowledge_span",
                render_class="evidence_items",
                title=f"Knowledge revision {revision.revision_number}",
                summary=excerpt[:160],
                content=content,
                provenance=_provenance(
                    contributor=self.name,
                    source_kind="knowledge_pack_revision",
                    source_key=(_normalize_revision_source_key(revision)),
                    source_id=None if revision.id is None else str(revision.id),
                    canonical_locator=(
                        None
                        if revision.id is None
                        else f"knowledge-pack-revision:{revision.id}"
                    ),
                    segment_id=(
                        None if revision.id is None else str(revision.revision_number)
                    ),
                    locale=revision.locale,
                    category=revision.category,
                    tenant_id=request.scope.tenant_id,
                    trace_id=request.trace_id,
                ),
                trust=0.95,
                freshness=1.0 if revision.published_at else 0.5,
                estimated_token_cost=_estimate_token_cost(content),
                sensitivity=("governed",),
            )
            candidates.append(
                ContextCandidate(artifact=artifact, contributor=self.name, priority=60)
            )
        return candidates


class ChannelOrchestrationContributor(IContextContributor):
    """Emit conversation/work-item/routing overlays."""

    name = "channel_orchestration"

    def __init__(
        self,
        *,
        conversation_state_service: ConversationStateService,
        work_item_service: WorkItemService,
    ) -> None:
        self._conversation_state_service = conversation_state_service
        self._work_item_service = work_item_service

    async def collect(
        self,
        request: ContextTurnRequest,
        *,
        policy: ContextPolicy,
        state: ContextState | None,
    ) -> list[ContextCandidate]:
        _ = policy
        _ = state
        tenant_id = _parse_tenant_uuid(request.scope)
        sender_key = request.scope.sender_id or request.scope.room_id
        if sender_key is None:
            return []

        conversation_rows = await self._conversation_state_service.list(
            filter_groups=[
                FilterGroup(where={"tenant_id": tenant_id, "sender_key": sender_key}),
            ],
            order_by=[OrderBy("updated_at", descending=True)],
            limit=1,
        )
        conversation = conversation_rows[0] if conversation_rows else None

        work_item = None
        if request.trace_id:
            work_items = await self._work_item_service.list(
                filter_groups=[
                    FilterGroup(
                        where={"tenant_id": tenant_id, "trace_id": request.trace_id}
                    ),
                ],
                order_by=[OrderBy("updated_at", descending=True)],
                limit=1,
            )
            work_item = work_items[0] if work_items else None

        if conversation is None and work_item is None:
            return []

        content = {
            "conversation": (
                None
                if conversation is None
                else {
                    "status": conversation.status,
                    "route_key": conversation.route_key,
                    "assigned_queue_name": conversation.assigned_queue_name,
                    "assigned_service_key": conversation.assigned_service_key,
                    "fallback_mode": conversation.fallback_mode,
                    "fallback_target": conversation.fallback_target,
                    "fallback_reason": conversation.fallback_reason,
                    "is_fallback_active": conversation.is_fallback_active,
                    "is_throttled": conversation.is_throttled,
                }
            ),
            "work_item": (
                None
                if work_item is None
                else {
                    "trace_id": work_item.trace_id,
                    "linked_case_id": (
                        None
                        if work_item.linked_case_id is None
                        else str(work_item.linked_case_id)
                    ),
                    "linked_workflow_instance_id": (
                        None
                        if work_item.linked_workflow_instance_id is None
                        else str(work_item.linked_workflow_instance_id)
                    ),
                }
            ),
        }
        artifact = ContextArtifact(
            artifact_id=f"channel-orchestration:{sender_key}",
            lane="operational_overlay",
            kind="channel_overlay",
            render_class="operational_overlay_items",
            title="Operational channel overlay",
            summary="Conversation routing and work-item state.",
            content=content,
            provenance=_provenance(
                contributor=self.name,
                source_kind="channel_orchestration",
                source_key=sender_key,
                canonical_locator=f"channel-orchestration:{sender_key}",
                tenant_id=request.scope.tenant_id,
                trace_id=request.trace_id,
            ),
            trust=0.95,
            freshness=0.95,
            estimated_token_cost=_estimate_token_cost(content),
        )
        return [ContextCandidate(artifact=artifact, contributor=self.name, priority=80)]


class OpsCaseContributor(IContextContributor):
    """Emit linked case summary and recent events."""

    name = "ops_case"

    def __init__(
        self,
        *,
        case_service: CaseService,
        case_event_service: CaseEventService,
    ) -> None:
        self._case_service = case_service
        self._case_event_service = case_event_service

    async def collect(
        self,
        request: ContextTurnRequest,
        *,
        policy: ContextPolicy,
        state: ContextState | None,
    ) -> list[ContextCandidate]:
        _ = policy
        _ = state
        case_id = request.scope.case_id or request.ingress_metadata.get(
            "linked_case_id"
        )
        if not isinstance(case_id, str) or case_id.strip() == "":
            return []
        tenant_id = _parse_tenant_uuid(request.scope)
        case = await self._case_service.get(
            {"tenant_id": tenant_id, "id": uuid.UUID(case_id)}
        )
        if case is None:
            return []
        events = await self._case_event_service.list(
            filter_groups=[
                FilterGroup(where={"tenant_id": tenant_id, "case_id": case.id})
            ],
            order_by=[OrderBy("occurred_at", descending=True)],
            limit=5,
        )
        content = {
            "case_number": case.case_number,
            "title": case.title,
            "status": case.status,
            "priority": case.priority,
            "severity": case.severity,
            "queue_name": case.queue_name,
            "owner_user_id": (
                None if case.owner_user_id is None else str(case.owner_user_id)
            ),
            "resolution_summary": case.resolution_summary,
            "recent_events": [
                {
                    "event_type": event.event_type,
                    "status_from": event.status_from,
                    "status_to": event.status_to,
                    "note": event.note,
                }
                for event in events
            ],
        }
        artifact = ContextArtifact(
            artifact_id=f"case:{case.id}",
            lane="operational_overlay",
            kind="case_overlay",
            render_class="operational_overlay_items",
            title=case.title,
            summary=case.resolution_summary or case.status,
            content=content,
            provenance=_provenance(
                contributor=self.name,
                source_kind="ops_case",
                source_key=case.case_number or str(case.id),
                source_id=str(case.id),
                canonical_locator=f"ops-case:{case.id}",
                category=case.queue_name,
                tenant_id=request.scope.tenant_id,
                trace_id=request.trace_id,
            ),
            trust=0.95,
            freshness=0.9,
            estimated_token_cost=_estimate_token_cost(content),
        )
        return [ContextCandidate(artifact=artifact, contributor=self.name, priority=75)]


class AuditContributor(IContextContributor):
    """Emit recent audit-trace timeline artifacts when trace context exists."""

    name = "audit"

    def __init__(self, *, audit_trace_service: AuditBizTraceEventService) -> None:
        self._audit_trace_service = audit_trace_service

    async def collect(
        self,
        request: ContextTurnRequest,
        *,
        policy: ContextPolicy,
        state: ContextState | None,
    ) -> list[ContextCandidate]:
        _ = policy
        _ = state
        if not request.trace_id:
            return []
        tenant_id = _parse_tenant_uuid(request.scope)
        rows = await self._audit_trace_service.list(
            filter_groups=[
                FilterGroup(
                    where={"tenant_id": tenant_id, "trace_id": request.trace_id}
                ),
            ],
            order_by=[OrderBy("occurred_at", descending=True)],
            limit=10,
        )
        if not rows:
            return []
        content = {
            "events": [
                {
                    "stage": row.stage,
                    "source_plugin": row.source_plugin,
                    "action_name": row.action_name,
                    "details_json": row.details_json,
                }
                for row in reversed(list(rows))
            ]
        }
        artifact = ContextArtifact(
            artifact_id=f"audit:{request.trace_id}",
            lane="operational_overlay",
            kind="audit_trace",
            render_class="operational_overlay_items",
            title="Audit trace",
            summary="Recent business trace events.",
            content=content,
            provenance=_provenance(
                contributor=self.name,
                source_kind="audit_biz_trace",
                source_key=request.trace_id,
                source_id=request.trace_id,
                canonical_locator=f"audit-trace:{request.trace_id}",
                tenant_id=request.scope.tenant_id,
                trace_id=request.trace_id,
            ),
            trust=0.9,
            freshness=0.9,
            estimated_token_cost=_estimate_token_cost(content),
            sensitivity=("audit",),
        )
        return [ContextCandidate(artifact=artifact, contributor=self.name, priority=50)]


class MemoryContributor(IContextContributor):
    """Emit long-term memory records relevant to the scoped conversation."""

    name = "memory"

    def __init__(self, *, memory_service: ContextMemoryRecordService) -> None:
        self._memory_service = memory_service

    async def collect(
        self,
        request: ContextTurnRequest,
        *,
        policy: ContextPolicy,
        state: ContextState | None,
    ) -> list[ContextCandidate]:
        _ = state
        if not policy.retention.allow_long_term_memory:
            return []
        tenant_id = _parse_tenant_uuid(request.scope)
        rows = await self._memory_service.list(
            filter_groups=[
                FilterGroup(where={"tenant_id": tenant_id, "is_deleted": False})
            ],
            order_by=[OrderBy("updated_at", descending=True)],
            limit=50,
        )
        candidates: list[ContextCandidate] = []
        for row in rows:
            if not _memory_partition_matches(row.scope_partition, request.scope):
                continue
            if (
                request.scope.tenant_id == str(GLOBAL_TENANT_ID)
                and policy.retention.require_partition_for_global_memory
                and not row.scope_partition
            ):
                continue
            content = {
                "memory_type": row.memory_type,
                "content": row.content,
                "subject": row.subject,
            }
            artifact = ContextArtifact(
                artifact_id=f"memory:{row.id}",
                lane="evidence",
                kind="memory",
                render_class="evidence_items",
                title=row.subject,
                summary=(
                    None if row.memory_type is None else f"Memory: {row.memory_type}"
                ),
                content=content,
                provenance=_provenance(
                    contributor=self.name,
                    source_kind="memory_record",
                    source_key=_memory_source_key(row),
                    source_id=None if row.id is None else str(row.id),
                    canonical_locator=(
                        None if row.id is None else f"context-memory:{row.id}"
                    ),
                    metadata=dict(row.provenance or {}),
                    tenant_id=request.scope.tenant_id,
                    trace_id=request.trace_id,
                ),
                trust=float(row.confidence or 0.8),
                freshness=0.8,
                estimated_token_cost=_estimate_token_cost(content),
            )
            candidates.append(
                ContextCandidate(artifact=artifact, contributor=self.name, priority=40)
            )
        return candidates

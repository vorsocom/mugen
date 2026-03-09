"""Runtime services for the context_engine plugin."""

from __future__ import annotations

__all__ = [
    "ContextCacheRecordService",
    "ContextEventLogService",
    "ContextMemoryRecordService",
    "ContextStateSnapshotService",
    "ContextTraceService",
    "DefaultContextGuard",
    "DefaultContextPolicyResolver",
    "DefaultContextRanker",
    "DefaultMemoryWriter",
    "RelationalContextCache",
    "RelationalContextStateStore",
    "RelationalContextTraceSink",
]

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

from mugen.core.constants import GLOBAL_TENANT_ID
from mugen.core.contract.context import (
    ContextBudget,
    ContextCandidate,
    ContextCommitResult,
    ContextPolicy,
    ContextRedactionPolicy,
    ContextRetentionPolicy,
    ContextSelectionReason,
    ContextState,
    ContextTurnRequest,
    IContextCache,
    IContextGuard,
    IContextPolicyResolver,
    IContextRanker,
    IContextStateStore,
    IContextTraceSink,
    IMemoryWriter,
    MemoryWrite,
    MemoryWriteType,
    PreparedContextTurn,
    TurnOutcome,
)
from mugen.core.contract.gateway.completion import CompletionResponse
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup, OrderBy
from mugen.core.plugin.audit.service.audit_biz_trace_event import (
    AuditBizTraceEventService,
)
from mugen.core.plugin.context_engine.domain import (
    ContextCacheRecordDE,
    ContextContributorBindingDE,
    ContextEventLogDE,
    ContextMemoryRecordDE,
    ContextPolicyDE,
    ContextProfileDE,
    ContextSourceBindingDE,
    ContextStateSnapshotDE,
    ContextTraceDE,
    ContextTracePolicyDE,
)
from mugen.core.plugin.context_engine.service.admin_resource import (
    ContextContributorBindingService,
    ContextPolicyService,
    ContextProfileService,
    ContextSourceBindingService,
    ContextTracePolicyService,
)
from mugen.core.utility.context_runtime import (
    scope_key,
    scope_partition,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_tenant_uuid(value: str) -> uuid.UUID:
    return uuid.UUID(str(value))


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _request_client_profile_key(request: ContextTurnRequest) -> str | None:
    ingress_metadata = dict(request.ingress_metadata or {})
    ingress_route = ingress_metadata.get("ingress_route")
    route_value = None
    if isinstance(ingress_route, dict):
        route_value = _normalize_optional_text(ingress_route.get("client_profile_key"))
    if route_value is not None:
        return route_value
    return _normalize_optional_text(ingress_metadata.get("client_profile_key"))


def _assistant_text(
    *,
    completion: CompletionResponse | None,
    final_user_responses: list[dict[str, Any]],
) -> str | None:
    for response in final_user_responses:
        if response.get("type") != "text":
            continue
        content = response.get("content")
        if isinstance(content, str) and content.strip() != "":
            return content
    content = None if completion is None else completion.content
    if isinstance(content, str) and content.strip() != "":
        return content
    return None


class ContextStateSnapshotService(  # pylint: disable=too-few-public-methods
    IRelationalService[ContextStateSnapshotDE]
):
    """CRUD service for context state snapshots."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs) -> None:
        super().__init__(
            de_type=ContextStateSnapshotDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )


class ContextEventLogService(  # pylint: disable=too-few-public-methods
    IRelationalService[ContextEventLogDE]
):
    """CRUD service for context event log rows."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs) -> None:
        super().__init__(de_type=ContextEventLogDE, table=table, rsg=rsg, **kwargs)


class ContextMemoryRecordService(  # pylint: disable=too-few-public-methods
    IRelationalService[ContextMemoryRecordDE]
):
    """CRUD service for context memory rows."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs) -> None:
        super().__init__(
            de_type=ContextMemoryRecordDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )


class ContextCacheRecordService(  # pylint: disable=too-few-public-methods
    IRelationalService[ContextCacheRecordDE]
):
    """CRUD service for context cache rows."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs) -> None:
        super().__init__(de_type=ContextCacheRecordDE, table=table, rsg=rsg, **kwargs)


class ContextTraceService(  # pylint: disable=too-few-public-methods
    IRelationalService[ContextTraceDE]
):
    """CRUD service for context trace rows."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs) -> None:
        super().__init__(de_type=ContextTraceDE, table=table, rsg=rsg, **kwargs)


class DefaultContextPolicyResolver(IContextPolicyResolver):
    """Resolve context policy from ACP-managed plugin resources."""

    def __init__(
        self,
        *,
        profile_service: ContextProfileService,
        policy_service: ContextPolicyService,
        contributor_binding_service: ContextContributorBindingService,
        source_binding_service: ContextSourceBindingService,
        trace_policy_service: ContextTracePolicyService,
    ) -> None:
        self._profile_service = profile_service
        self._policy_service = policy_service
        self._contributor_binding_service = contributor_binding_service
        self._source_binding_service = source_binding_service
        self._trace_policy_service = trace_policy_service

    async def resolve_policy(self, request: ContextTurnRequest) -> ContextPolicy:
        tenant_id = _parse_tenant_uuid(request.scope.tenant_id)
        client_profile_key = _request_client_profile_key(request)

        profiles = await self._profile_service.list(
            filter_groups=[FilterGroup(where={"tenant_id": tenant_id, "is_active": True})],
            limit=200,
        )
        profile = self._select_profile(request.scope, client_profile_key, profiles)

        policies = await self._policy_service.list(
            filter_groups=[FilterGroup(where={"tenant_id": tenant_id, "is_active": True})],
            limit=200,
        )
        policy_row = self._select_policy(profile, policies)

        contributor_bindings = await self._contributor_binding_service.list(
            filter_groups=[
                FilterGroup(where={"tenant_id": tenant_id, "is_enabled": True}),
            ],
            limit=500,
        )
        source_bindings = await self._source_binding_service.list(
            filter_groups=[
                FilterGroup(where={"tenant_id": tenant_id, "is_enabled": True}),
            ],
            limit=500,
        )
        trace_policies = await self._trace_policy_service.list(
            filter_groups=[FilterGroup(where={"tenant_id": tenant_id, "is_active": True})],
            limit=50,
        )

        contributor_allow = tuple(
            binding.contributor_key
            for binding in contributor_bindings
            if self._binding_matches_scope(binding, request.scope)
            and binding.contributor_key is not None
        )
        source_allow = tuple(
            binding.source_kind
            for binding in source_bindings
            if self._source_binding_matches_scope(binding, request.scope)
            and binding.source_kind is not None
        )

        default_policy = self._default_policy(scope=request.scope)
        trace_policy = trace_policies[0] if trace_policies else None
        if policy_row is None:
            return ContextPolicy(
                profile_key=None if profile is None else profile.name,
                policy_key="default",
                budget=default_policy.budget,
                redaction=default_policy.redaction,
                retention=default_policy.retention,
                contributor_allow=contributor_allow,
                source_allow=source_allow,
                trace_enabled=(
                    default_policy.trace_enabled
                    if trace_policy is None
                    else bool(trace_policy.capture_prepare or trace_policy.capture_commit)
                ),
                cache_enabled=default_policy.cache_enabled,
                metadata={
                    "profile_name": None if profile is None else profile.name,
                    "persona": None if profile is None else getattr(profile, "persona", None),
                    "trace_policy_name": None if trace_policy is None else trace_policy.name,
                },
            )

        budget = self._budget_from_row(policy_row, default_policy.budget)
        redaction = self._redaction_from_row(policy_row, default_policy.redaction)
        retention = self._retention_from_row(policy_row, default_policy.retention)
        return ContextPolicy(
            profile_key=None if profile is None else profile.name,
            policy_key=policy_row.policy_key,
            budget=budget,
            redaction=redaction,
            retention=retention,
            contributor_allow=(
                tuple(policy_row.contributor_allow or ()) or contributor_allow
            ),
            contributor_deny=tuple(policy_row.contributor_deny or ()),
            source_allow=tuple(policy_row.source_allow or ()) or source_allow,
            source_deny=tuple(policy_row.source_deny or ()),
            trace_enabled=bool(policy_row.trace_enabled),
            cache_enabled=bool(policy_row.cache_enabled),
            metadata={
                "profile_name": None if profile is None else profile.name,
                "persona": None if profile is None else getattr(profile, "persona", None),
                "trace_policy_name": None if trace_policy is None else trace_policy.name,
                "trace_capture_selected": (
                    None
                    if trace_policy is None
                    else bool(trace_policy.capture_selected_items)
                ),
                "trace_capture_dropped": (
                    None
                    if trace_policy is None
                    else bool(trace_policy.capture_dropped_items)
                ),
                "source_bindings": [binding.source_key for binding in source_bindings],
            },
        )

    @staticmethod
    def _select_profile(
        scope,
        client_profile_key: str | None,
        profiles: list[ContextProfileDE],
    ) -> ContextProfileDE | None:
        matches = [
            profile
            for profile in profiles
            if getattr(profile, "platform", None) in (None, scope.platform)
            and getattr(profile, "channel_key", None) in (None, scope.channel_id)
            and getattr(profile, "client_profile_key", None) in (None, client_profile_key)
        ]
        if not matches:
            return None
        matches.sort(
            key=lambda profile: (
                0 if getattr(profile, "platform", None) == scope.platform else 1,
                0 if getattr(profile, "channel_key", None) == scope.channel_id else 1,
                (
                    0
                    if getattr(profile, "client_profile_key", None) == client_profile_key
                    else 1
                ),
                0 if getattr(profile, "is_default", None) else 1,
            )
        )
        return matches[0]

    @staticmethod
    def _select_policy(
        profile: ContextProfileDE | None,
        policies: list[ContextPolicyDE],
    ) -> ContextPolicyDE | None:
        if profile is not None and profile.policy_id is not None:
            for policy in policies:
                if policy.id == profile.policy_id:
                    return policy
        defaults = [policy for policy in policies if policy.is_default]
        if defaults:
            return defaults[0]
        return policies[0] if policies else None

    @staticmethod
    def _binding_matches_scope(binding: ContextContributorBindingDE, scope) -> bool:
        return binding.platform in (None, scope.platform) and binding.channel_key in (
            None,
            scope.channel_id,
        )

    @staticmethod
    def _source_binding_matches_scope(binding: ContextSourceBindingDE, scope) -> bool:
        return binding.platform in (None, scope.platform) and binding.channel_key in (
            None,
            scope.channel_id,
        )

    @staticmethod
    def _budget_from_row(
        row: ContextPolicyDE,
        default_budget: ContextBudget,
    ) -> ContextBudget:
        payload = dict(row.budget_json or {})
        return ContextBudget(
            max_total_tokens=int(payload.get("max_total_tokens", default_budget.max_total_tokens)),
            max_selected_artifacts=int(
                payload.get(
                    "max_selected_artifacts",
                    default_budget.max_selected_artifacts,
                )
            ),
            max_recent_turns=int(
                payload.get("max_recent_turns", default_budget.max_recent_turns)
            ),
            max_recent_messages=int(
                payload.get("max_recent_messages", default_budget.max_recent_messages)
            ),
            max_evidence_items=int(
                payload.get("max_evidence_items", default_budget.max_evidence_items)
            ),
            max_prefix_tokens=int(
                payload.get("max_prefix_tokens", default_budget.max_prefix_tokens)
            ),
        )

    @staticmethod
    def _redaction_from_row(
        row: ContextPolicyDE,
        default_policy: ContextRedactionPolicy,
    ) -> ContextRedactionPolicy:
        payload = dict(row.redaction_json or {})
        return ContextRedactionPolicy(
            redact_sensitive=bool(
                payload.get("redact_sensitive", default_policy.redact_sensitive)
            ),
            blocked_sensitivity_labels=tuple(
                payload.get(
                    "blocked_sensitivity_labels",
                    default_policy.blocked_sensitivity_labels,
                )
            ),
            allowed_sensitivity_labels=tuple(
                payload.get(
                    "allowed_sensitivity_labels",
                    default_policy.allowed_sensitivity_labels,
                )
            ),
        )

    @staticmethod
    def _retention_from_row(
        row: ContextPolicyDE,
        default_policy: ContextRetentionPolicy,
    ) -> ContextRetentionPolicy:
        payload = dict(row.retention_json or {})
        return ContextRetentionPolicy(
            allow_long_term_memory=bool(
                payload.get(
                    "allow_long_term_memory",
                    default_policy.allow_long_term_memory,
                )
            ),
            require_partition_for_global_memory=bool(
                payload.get(
                    "require_partition_for_global_memory",
                    default_policy.require_partition_for_global_memory,
                )
            ),
            memory_ttl_seconds=payload.get(
                "memory_ttl_seconds",
                default_policy.memory_ttl_seconds,
            ),
            trace_ttl_seconds=payload.get(
                "trace_ttl_seconds",
                default_policy.trace_ttl_seconds,
            ),
            cache_ttl_seconds=payload.get(
                "cache_ttl_seconds",
                default_policy.cache_ttl_seconds,
            ),
        )

    @staticmethod
    def _default_policy(scope) -> ContextPolicy:
        retention = ContextRetentionPolicy(
            allow_long_term_memory=True,
            require_partition_for_global_memory=True,
            cache_ttl_seconds=300,
            trace_ttl_seconds=86400,
            memory_ttl_seconds=None,
        )
        if scope.tenant_id == str(GLOBAL_TENANT_ID):
            retention = ContextRetentionPolicy(
                allow_long_term_memory=True,
                require_partition_for_global_memory=True,
                cache_ttl_seconds=300,
                trace_ttl_seconds=86400,
                memory_ttl_seconds=None,
            )
        return ContextPolicy(
            budget=ContextBudget(),
            redaction=ContextRedactionPolicy(
                redact_sensitive=True,
            ),
            retention=retention,
            trace_enabled=True,
            cache_enabled=True,
            metadata={"default_policy": True},
        )


class RelationalContextStateStore(IContextStateStore):
    """Bounded state store backed by relational snapshot and event-log tables."""

    def __init__(
        self,
        *,
        snapshot_service: ContextStateSnapshotService,
        event_log_service: ContextEventLogService,
    ) -> None:
        self._snapshot_service = snapshot_service
        self._event_log_service = event_log_service

    async def load(self, request: ContextTurnRequest) -> ContextState | None:
        tenant_id = _parse_tenant_uuid(request.scope.tenant_id)
        scope_key_value = scope_key(request.scope)
        row = await self._snapshot_service.get(
            {"tenant_id": tenant_id, "scope_key": scope_key_value}
        )
        if row is None:
            return None
        return ContextState(
            current_objective=row.current_objective,
            entities=dict(row.entities or {}),
            constraints=list(row.constraints or []),
            unresolved_slots=list(row.unresolved_slots or []),
            commitments=list(row.commitments or []),
            safety_flags=list(row.safety_flags or []),
            routing=dict(row.routing or {}),
            summary=row.summary,
            revision=int(row.revision or 0),
            metadata=dict(row.attributes or {}),
        )

    async def save(
        self,
        *,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
        completion: CompletionResponse | None,
        final_user_responses: list[dict[str, Any]],
        outcome: TurnOutcome,
    ) -> ContextState:
        tenant_id = _parse_tenant_uuid(request.scope.tenant_id)
        scope_key_value = scope_key(request.scope)
        existing = await self._snapshot_service.get(
            {"tenant_id": tenant_id, "scope_key": scope_key_value}
        )
        assistant_response = _assistant_text(
            completion=completion,
            final_user_responses=final_user_responses,
        )
        next_revision = int(0 if existing is None else existing.revision or 0) + 1
        next_state = ContextState(
            current_objective=self._objective_from_request(request),
            entities=dict((existing.entities if existing is not None else {}) or {}),
            constraints=list(
                (existing.constraints if existing is not None else []) or []
            ),
            unresolved_slots=list(
                (existing.unresolved_slots if existing is not None else []) or []
            ),
            commitments=list(
                (existing.commitments if existing is not None else []) or []
            ),
            safety_flags=list(
                (existing.safety_flags if existing is not None else []) or []
            ),
            routing={
                "conversation_id": request.scope.conversation_id,
                "case_id": request.scope.case_id,
                "workflow_id": request.scope.workflow_id,
                "tenant_resolution": request.ingress_metadata.get("tenant_resolution"),
            },
            summary=assistant_response,
            revision=next_revision,
            metadata={
                "message_id": request.message_id,
                "trace_id": request.trace_id,
                "outcome": outcome.value,
            },
        )
        payload = {
            "tenant_id": tenant_id,
            "scope_key": scope_key_value,
            "platform": request.scope.platform,
            "channel_id": request.scope.channel_id,
            "room_id": request.scope.room_id,
            "sender_id": request.scope.sender_id,
            "conversation_id": request.scope.conversation_id,
            "case_id": request.scope.case_id,
            "workflow_id": request.scope.workflow_id,
            "current_objective": next_state.current_objective,
            "entities": next_state.entities,
            "constraints": next_state.constraints,
            "unresolved_slots": next_state.unresolved_slots,
            "commitments": next_state.commitments,
            "safety_flags": next_state.safety_flags,
            "routing": next_state.routing,
            "summary": next_state.summary,
            "revision": next_state.revision,
            "last_message_id": request.message_id,
            "last_trace_id": request.trace_id,
            "attributes": next_state.metadata,
        }
        if existing is None or existing.id is None:
            await self._snapshot_service.create(payload)
        else:
            await self._snapshot_service.update(
                {"tenant_id": tenant_id, "id": existing.id},
                payload,
            )

        await self._append_turn_events(
            request=request,
            assistant_response=assistant_response,
        )
        return next_state

    async def clear(self, request: ContextTurnRequest) -> None:
        tenant_id = _parse_tenant_uuid(request.scope.tenant_id)
        scope_key_value = scope_key(request.scope)
        await self._snapshot_service.delete(
            {"tenant_id": tenant_id, "scope_key": scope_key_value}
        )
        await self._event_log_service._rsg.delete_many(  # pylint: disable=protected-access
            self._event_log_service.table,
            {"tenant_id": tenant_id, "scope_key": scope_key_value},
        )

    async def _append_turn_events(
        self,
        *,
        request: ContextTurnRequest,
        assistant_response: str | None,
    ) -> None:
        tenant_id = _parse_tenant_uuid(request.scope.tenant_id)
        scope_key_value = scope_key(request.scope)
        sequence = await self._event_log_service.count(
            filter_groups=[
                FilterGroup(
                    where={"tenant_id": tenant_id, "scope_key": scope_key_value}
                )
            ]
        )
        next_sequence = sequence + 1
        await self._event_log_service.create(
            {
                "tenant_id": tenant_id,
                "scope_key": scope_key_value,
                "sequence_no": next_sequence,
                "role": "user",
                "content": request.user_message,
                "message_id": request.message_id,
                "trace_id": request.trace_id,
                "source": "user_turn",
                "occurred_at": _utc_now(),
            }
        )
        if assistant_response is None:
            return
        await self._event_log_service.create(
            {
                "tenant_id": tenant_id,
                "scope_key": scope_key_value,
                "sequence_no": next_sequence + 1,
                "role": "assistant",
                "content": assistant_response,
                "message_id": request.message_id,
                "trace_id": request.trace_id,
                "source": "assistant_turn",
                "occurred_at": _utc_now(),
            }
        )

    @staticmethod
    def _objective_from_request(request: ContextTurnRequest) -> str:
        if isinstance(request.user_message, str):
            return request.user_message[:512]
        return str(request.user_message)[:512]


class RelationalContextCache(IContextCache):
    """Tenant-safe cache with enforced tenant-prefixed keys."""

    def __init__(self, *, cache_service: ContextCacheRecordService) -> None:
        self._cache_service = cache_service

    async def get(self, *, namespace: str, key: str) -> Any:
        tenant_id, cache_key = self._parse_key(key)
        row = await self._cache_service.get(
            {
                "tenant_id": tenant_id,
                "namespace": namespace,
                "cache_key": cache_key,
            }
        )
        if row is None:
            return None
        now = _utc_now()
        if row.expires_at is not None and row.expires_at <= now:
            await self._cache_service.delete(
                {
                    "tenant_id": tenant_id,
                    "namespace": namespace,
                    "cache_key": cache_key,
                }
            )
            return None
        await self._cache_service.update(
            {"tenant_id": tenant_id, "id": row.id},
            {
                "hit_count": int(row.hit_count or 0) + 1,
                "last_hit_at": now,
            },
        )
        return row.payload

    async def put(
        self,
        *,
        namespace: str,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> None:
        tenant_id, cache_key = self._parse_key(key)
        existing = await self._cache_service.get(
            {
                "tenant_id": tenant_id,
                "namespace": namespace,
                "cache_key": cache_key,
            }
        )
        expires_at = None
        if isinstance(ttl_seconds, int) and ttl_seconds > 0:
            expires_at = _utc_now().replace(microsecond=0) + timedelta(seconds=ttl_seconds)
        payload = {
            "tenant_id": tenant_id,
            "namespace": namespace,
            "cache_key": cache_key,
            "payload": value,
            "expires_at": expires_at,
        }
        if existing is None or existing.id is None:
            await self._cache_service.create(payload)
        else:
            await self._cache_service.update(
                {"tenant_id": tenant_id, "id": existing.id},
                payload,
            )

    async def invalidate(self, *, namespace: str, key_prefix: str) -> int:
        tenant_id, cache_prefix = self._parse_key(key_prefix)
        rows = await self._cache_service.list(
            filter_groups=[
                FilterGroup(where={"tenant_id": tenant_id, "namespace": namespace}),
            ],
            limit=5_000,
        )
        deleted = 0
        for row in rows:
            if not isinstance(row.cache_key, str):
                continue
            if not row.cache_key.startswith(cache_prefix):
                continue
            await self._cache_service.delete({"tenant_id": tenant_id, "id": row.id})
            deleted += 1
        return deleted

    @staticmethod
    def _parse_key(key: str) -> tuple[uuid.UUID, str]:
        if not isinstance(key, str) or not key.startswith("tenant:"):
            raise RuntimeError("Context cache keys must include tenant:<uuid> prefix.")
        _, tenant_text, cache_key = key.split(":", 2)
        return uuid.UUID(tenant_text), cache_key


class RelationalContextTraceSink(IContextTraceSink):
    """Trace sink backed by plugin trace rows and optional audit bridge writes."""

    def __init__(
        self,
        *,
        trace_service: ContextTraceService,
        audit_trace_service: AuditBizTraceEventService | None = None,
    ) -> None:
        self._trace_service = trace_service
        self._audit_trace_service = audit_trace_service

    async def record_prepare(
        self,
        *,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
    ) -> None:
        if not prepared.bundle.policy.trace_enabled:
            return
        await self._persist_trace(
            request=request,
            stage="prepare",
            payload=prepared.trace,
            selected_items=prepared.trace.get("selected", []),
            dropped_items=prepared.trace.get("dropped", []),
        )

    async def record_commit(
        self,
        *,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
        completion: CompletionResponse | None,
        final_user_responses: list[dict[str, Any]],
        outcome: TurnOutcome,
        result: ContextCommitResult,
    ) -> None:
        if not prepared.bundle.policy.trace_enabled:
            return
        payload = {
            "completion_model": None if completion is None else completion.model,
            "completion_stop_reason": None if completion is None else completion.stop_reason,
            "final_user_responses": final_user_responses,
            "outcome": outcome.value,
            "commit_result": {
                "commit_token": result.commit_token,
                "state_revision": result.state_revision,
                "memory_writes": [asdict(write) for write in result.memory_writes],
                "cache_updates": result.cache_updates,
            },
        }
        await self._persist_trace(
            request=request,
            stage="commit",
            payload=payload,
            selected_items=prepared.trace.get("selected", []),
            dropped_items=prepared.trace.get("dropped", []),
        )

    async def _persist_trace(
        self,
        *,
        request: ContextTurnRequest,
        stage: str,
        payload: dict[str, Any],
        selected_items: list[dict[str, Any]],
        dropped_items: list[dict[str, Any]],
    ) -> None:
        tenant_id = _parse_tenant_uuid(request.scope.tenant_id)
        trace_id = request.trace_id or request.message_id or str(uuid.uuid4())
        await self._trace_service.create(
            {
                "tenant_id": tenant_id,
                "scope_key": scope_key(request.scope),
                "trace_id": trace_id,
                "message_id": request.message_id,
                "stage": stage,
                "selected_items": selected_items,
                "dropped_items": dropped_items,
                "payload": payload,
                "occurred_at": _utc_now(),
            }
        )
        if self._audit_trace_service is None:
            return
        await self._audit_trace_service.create(
            {
                "tenant_id": tenant_id,
                "trace_id": trace_id,
                "source_plugin": "context_engine",
                "entity_set": "ContextTrace",
                "action_name": stage,
                "stage": stage,
                "details_json": payload,
                "occurred_at": _utc_now(),
            }
        )


class DefaultMemoryWriter(IMemoryWriter):
    """Persist derived memory records after final output is known."""

    def __init__(self, *, memory_service: ContextMemoryRecordService) -> None:
        self._memory_service = memory_service

    async def persist(
        self,
        *,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
        completion: CompletionResponse | None,
        final_user_responses: list[dict[str, Any]],
        outcome: TurnOutcome,
    ) -> list[MemoryWrite]:
        if outcome is not TurnOutcome.COMPLETED:
            return []
        if request.scope.tenant_id == str(GLOBAL_TENANT_ID) and not (
            request.scope.sender_id or request.scope.conversation_id
        ):
            return []
        assistant_response = _assistant_text(
            completion=completion,
            final_user_responses=final_user_responses,
        )
        writes = self._derive_writes(
            request=request,
            prepared=prepared,
            assistant_response=assistant_response,
        )
        if not writes:
            return []
        tenant_id = _parse_tenant_uuid(request.scope.tenant_id)
        partition = scope_partition(request.scope)
        for write in writes:
            await self._memory_service.create(
                {
                    "tenant_id": tenant_id,
                    "scope_partition": partition,
                    "memory_type": write.write_type.value,
                    "memory_key": write.key,
                    "subject": write.subject,
                    "content": write.content,
                    "provenance": asdict(write.provenance),
                    "confidence": write.confidence,
                    "expires_at": self._expires_at(write.ttl_seconds),
                    "is_deleted": False,
                    "tags": list(write.tags),
                    "commit_token": prepared.commit_token,
                    "attributes": dict(write.metadata),
                }
            )
        return writes

    def _derive_writes(
        self,
        *,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
        assistant_response: str | None,
    ) -> list[MemoryWrite]:
        provenance = prepared.bundle.selected_candidates[0].artifact.provenance if (
            prepared.bundle.selected_candidates
        ) else None
        if provenance is None:
            from mugen.core.contract.context import ContextProvenance

            provenance = ContextProvenance(
                contributor="context_engine",
                source_kind="turn_commit",
                tenant_id=request.scope.tenant_id,
                trace_id=request.trace_id,
            )

        writes: list[MemoryWrite] = [
            MemoryWrite(
                write_type=MemoryWriteType.EPISODE,
                content={
                    "user_message": request.user_message,
                    "assistant_response": assistant_response,
                },
                provenance=provenance,
                scope_partition=scope_partition(request.scope),
                key=request.trace_id or request.message_id,
                subject=request.scope.sender_id,
                metadata={"scope_key": scope_key(request.scope)},
            )
        ]

        if isinstance(request.user_message, str):
            lower = request.user_message.lower()
            if "i prefer " in lower:
                writes.append(
                    MemoryWrite(
                        write_type=MemoryWriteType.PREFERENCE,
                        content={"statement": request.user_message},
                        provenance=provenance,
                        scope_partition=scope_partition(request.scope),
                        subject=request.scope.sender_id,
                    )
                )
            if "my name is " in lower:
                writes.append(
                    MemoryWrite(
                        write_type=MemoryWriteType.FACT,
                        content={"statement": request.user_message},
                        provenance=provenance,
                        scope_partition=scope_partition(request.scope),
                        subject=request.scope.sender_id,
                    )
                )
        return writes

    @staticmethod
    def _expires_at(ttl_seconds: int | None) -> datetime | None:
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            return None
        return _utc_now() + timedelta(seconds=ttl_seconds)


class DefaultContextGuard(IContextGuard):
    """Guard candidates for tenant isolation and sensitivity policy."""

    name = "default_guard"

    async def apply(
        self,
        request: ContextTurnRequest,
        candidates: list[ContextCandidate],
        *,
        policy: ContextPolicy,
        state: ContextState | None,
    ) -> list[ContextCandidate]:
        _ = state
        guarded: list[ContextCandidate] = []
        blocked = set(policy.redaction.blocked_sensitivity_labels)
        for candidate in candidates:
            provenance_tenant = candidate.artifact.provenance.tenant_id
            if provenance_tenant is not None and provenance_tenant != request.scope.tenant_id:
                guarded.append(
                    ContextCandidate(
                        artifact=candidate.artifact,
                        contributor=candidate.contributor,
                        priority=candidate.priority,
                        score=candidate.score,
                        selected=False,
                        selection_reason=ContextSelectionReason.DROPPED_TENANT_MISMATCH,
                        reason_detail="tenant_id_mismatch",
                        metadata=dict(candidate.metadata),
                    )
                )
                continue

            sensitivity = set(candidate.artifact.sensitivity)
            if blocked and sensitivity.intersection(blocked):
                guarded.append(
                    ContextCandidate(
                        artifact=candidate.artifact,
                        contributor=candidate.contributor,
                        priority=candidate.priority,
                        score=candidate.score,
                        selected=False,
                        selection_reason=ContextSelectionReason.DROPPED_GUARD,
                        reason_detail="blocked_sensitivity",
                        metadata=dict(candidate.metadata),
                    )
                )
                continue

            if (
                request.scope.tenant_id == str(GLOBAL_TENANT_ID)
                and candidate.artifact.kind == "memory"
                and not (request.scope.sender_id or request.scope.conversation_id)
            ):
                guarded.append(
                    ContextCandidate(
                        artifact=candidate.artifact,
                        contributor=candidate.contributor,
                        priority=candidate.priority,
                        score=candidate.score,
                        selected=False,
                        selection_reason=ContextSelectionReason.DROPPED_POLICY,
                        reason_detail="global_memory_requires_partition",
                        metadata=dict(candidate.metadata),
                    )
                )
                continue

            guarded.append(candidate)
        return guarded


class DefaultContextRanker(IContextRanker):
    """Simple default ranker with lane, trust, freshness, and cost weighting."""

    name = "default_ranker"

    _lane_bonus = {
        "system_persona_policy": 100.0,
        "bounded_control_state": 90.0,
        "operational_overlay": 80.0,
        "evidence": 70.0,
        "recent_turn": 60.0,
    }

    async def rank(
        self,
        request: ContextTurnRequest,
        candidates: list[ContextCandidate],
        *,
        policy: ContextPolicy,
        state: ContextState | None,
    ) -> list[ContextCandidate]:
        _ = request
        _ = policy
        _ = state
        ranked: list[ContextCandidate] = []
        for candidate in candidates:
            artifact = candidate.artifact
            score = self._lane_bonus.get(artifact.lane, 0.0)
            score += float(artifact.trust or 0.0) * 10.0
            score += float(artifact.freshness or 0.0) * 5.0
            score += float(candidate.priority) * 0.1
            score -= min(float(artifact.estimated_token_cost or 0) / 100.0, 10.0)
            ranked.append(
                ContextCandidate(
                    artifact=artifact,
                    contributor=candidate.contributor,
                    priority=candidate.priority,
                    score=score,
                    selected=candidate.selected,
                    selection_reason=candidate.selection_reason,
                    reason_detail=candidate.reason_detail,
                    metadata=dict(candidate.metadata),
                )
            )
        return ranked

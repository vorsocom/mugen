"""Runtime services for the context_engine plugin."""

from __future__ import annotations

__all__ = [
    "ContextCacheRecordService",
    "ContextCommitLedgerService",
    "ContextEventLogService",
    "ContextMemoryRecordService",
    "ContextStateSnapshotService",
    "ContextTraceService",
    "DefaultContextGuard",
    "DefaultContextPolicyResolver",
    "DefaultContextRanker",
    "DefaultMemoryWriter",
    "RecentTurnMessageRenderer",
    "RelationalContextCache",
    "RelationalContextCommitStore",
    "RelationalContextStateStore",
    "RelationalContextTraceSink",
    "StructuredLaneRenderer",
]

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

from mugen.core.constants import GLOBAL_TENANT_ID
from mugen.core.contract.context import (
    ContextBudget,
    ContextCandidate,
    ContextCommitCheck,
    ContextCommitResult,
    ContextCommitState,
    ContextGuardResult,
    ContextLaneBudget,
    ContextPolicy,
    ContextProvenance,
    ContextRedactionPolicy,
    ContextRetentionPolicy,
    ContextSelectionReason,
    ContextState,
    ContextSourcePolicyEffect,
    ContextSourceRef,
    ContextSourceRule,
    ContextTurnRequest,
    IContextArtifactRenderer,
    IContextCache,
    IContextCommitStore,
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
from mugen.core.contract.gateway.completion import CompletionMessage, CompletionResponse
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup, OrderBy
from mugen.core.plugin.audit.service.audit_biz_trace_event import (
    AuditBizTraceEventService,
)
from mugen.core.plugin.context_engine.domain import (
    ContextCacheRecordDE,
    ContextCommitLedgerDE,
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


def _request_service_route_key(request: ContextTurnRequest) -> str | None:
    ingress_metadata = dict(request.ingress_metadata or {})
    ingress_route = ingress_metadata.get("ingress_route")
    route_value = None
    if isinstance(ingress_route, dict):
        route_value = _normalize_optional_text(ingress_route.get("service_route_key"))
    if route_value is not None:
        return route_value
    return _normalize_optional_text(ingress_metadata.get("service_route_key"))


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


class _StateSnapshotConflictError(RuntimeError):
    """Signal an optimistic-concurrency conflict while saving state."""


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


class ContextCommitLedgerService(  # pylint: disable=too-few-public-methods
    IRelationalService[ContextCommitLedgerDE]
):
    """CRUD service for context commit-ledger rows."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs) -> None:
        super().__init__(
            de_type=ContextCommitLedgerDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )


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
        service_route_key = _request_service_route_key(request)
        client_profile_key = _request_client_profile_key(request)

        profiles = await self._profile_service.list(
            filter_groups=[
                FilterGroup(where={"tenant_id": tenant_id, "is_active": True})
            ],
            limit=200,
        )
        profile = self._select_profile(
            request.scope,
            service_route_key,
            client_profile_key,
            profiles,
        )

        policies = await self._policy_service.list(
            filter_groups=[
                FilterGroup(where={"tenant_id": tenant_id, "is_active": True})
            ],
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
            filter_groups=[
                FilterGroup(where={"tenant_id": tenant_id, "is_active": True})
            ],
            limit=50,
        )

        contributor_allow = tuple(
            binding.contributor_key
            for binding in contributor_bindings
            if self._binding_matches_scope(binding, request.scope, service_route_key)
            and binding.contributor_key is not None
        )
        source_allow = tuple(
            binding.source_kind
            for binding in source_bindings
            if self._source_binding_matches_scope(
                binding,
                request.scope,
                service_route_key,
            )
            and binding.source_kind is not None
        )
        source_rules = tuple(
            self._source_rule_from_binding(binding)
            for binding in source_bindings
            if self._source_binding_matches_scope(
                binding,
                request.scope,
                service_route_key,
            )
            and binding.source_kind is not None
        )

        default_policy = self._default_policy(scope=request.scope)
        trace_policy = trace_policies[0] if trace_policies else None
        trace_capture_prepare = (
            default_policy.trace_capture_prepare
            if trace_policy is None
            else bool(trace_policy.capture_prepare)
        )
        trace_capture_commit = (
            default_policy.trace_capture_commit
            if trace_policy is None
            else bool(trace_policy.capture_commit)
        )
        trace_capture_selected = (
            default_policy.trace_capture_selected
            if trace_policy is None
            else bool(trace_policy.capture_selected_items)
        )
        trace_capture_dropped = (
            default_policy.trace_capture_dropped
            if trace_policy is None
            else bool(trace_policy.capture_dropped_items)
        )
        if policy_row is None:
            return ContextPolicy(
                profile_key=None if profile is None else profile.name,
                policy_key="default",
                budget=default_policy.budget,
                redaction=default_policy.redaction,
                retention=default_policy.retention,
                contributor_allow=self._dedupe_texts(contributor_allow),
                source_allow=self._dedupe_texts(source_allow),
                source_rules=source_rules,
                trace_enabled=bool(trace_capture_prepare or trace_capture_commit),
                trace_capture_prepare=trace_capture_prepare,
                trace_capture_commit=trace_capture_commit,
                trace_capture_selected=trace_capture_selected,
                trace_capture_dropped=trace_capture_dropped,
                cache_enabled=default_policy.cache_enabled,
                metadata={
                    "profile_name": None if profile is None else profile.name,
                    "persona": (
                        None if profile is None else getattr(profile, "persona", None)
                    ),
                    "service_route_key": service_route_key,
                    "trace_policy_name": (
                        None if trace_policy is None else trace_policy.name
                    ),
                    "source_bindings": [
                        binding.source_key for binding in source_bindings
                    ],
                },
            )

        budget = self._budget_from_row(policy_row, default_policy.budget)
        redaction = self._redaction_from_row(policy_row, default_policy.redaction)
        retention = self._retention_from_row(policy_row, default_policy.retention)
        resolved_trace_enabled = bool(policy_row.trace_enabled) and bool(
            trace_capture_prepare or trace_capture_commit
        )
        return ContextPolicy(
            profile_key=None if profile is None else profile.name,
            policy_key=policy_row.policy_key,
            budget=budget,
            redaction=redaction,
            retention=retention,
            contributor_allow=(
                self._dedupe_texts(tuple(policy_row.contributor_allow or ()))
                or self._dedupe_texts(contributor_allow)
            ),
            contributor_deny=tuple(policy_row.contributor_deny or ()),
            source_allow=(
                self._dedupe_texts(tuple(policy_row.source_allow or ()))
                or self._dedupe_texts(source_allow)
            ),
            source_deny=tuple(policy_row.source_deny or ()),
            source_rules=self._merge_source_rules(
                binding_rules=source_rules,
                allow_kinds=tuple(policy_row.source_allow or ()),
                deny_kinds=tuple(policy_row.source_deny or ()),
            ),
            trace_enabled=resolved_trace_enabled,
            trace_capture_prepare=trace_capture_prepare,
            trace_capture_commit=trace_capture_commit,
            trace_capture_selected=trace_capture_selected,
            trace_capture_dropped=trace_capture_dropped,
            cache_enabled=bool(policy_row.cache_enabled),
            metadata={
                "profile_name": None if profile is None else profile.name,
                "persona": (
                    None if profile is None else getattr(profile, "persona", None)
                ),
                "service_route_key": service_route_key,
                "trace_policy_name": (
                    None if trace_policy is None else trace_policy.name
                ),
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
        service_route_key: str | None,
        client_profile_key: str | None,
        profiles: list[ContextProfileDE],
    ) -> ContextProfileDE | None:
        matches = [
            profile
            for profile in profiles
            if getattr(profile, "platform", None) in (None, scope.platform)
            and getattr(profile, "channel_key", None) in (None, scope.channel_id)
            and getattr(profile, "service_route_key", None)
            in (None, service_route_key)
            and getattr(profile, "client_profile_key", None)
            in (None, client_profile_key)
        ]
        if not matches:
            return None
        matches.sort(
            key=lambda profile: (
                0 if getattr(profile, "platform", None) == scope.platform else 1,
                0 if getattr(profile, "channel_key", None) == scope.channel_id else 1,
                (
                    0
                    if getattr(profile, "service_route_key", None)
                    == service_route_key
                    else 1
                ),
                (
                    0
                    if getattr(profile, "client_profile_key", None)
                    == client_profile_key
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
    def _binding_matches_scope(
        binding: ContextContributorBindingDE,
        scope,
        service_route_key: str | None,
    ) -> bool:
        return (
            binding.platform in (None, scope.platform)
            and binding.channel_key in (
                None,
                scope.channel_id,
            )
            and getattr(binding, "service_route_key", None)
            in (None, service_route_key)
        )

    @staticmethod
    def _source_binding_matches_scope(
        binding: ContextSourceBindingDE,
        scope,
        service_route_key: str | None,
    ) -> bool:
        return (
            binding.platform in (None, scope.platform)
            and binding.channel_key in (
                None,
                scope.channel_id,
            )
            and getattr(binding, "service_route_key", None)
            in (None, service_route_key)
        )

    @staticmethod
    def _budget_from_row(
        row: ContextPolicyDE,
        default_budget: ContextBudget,
    ) -> ContextBudget:
        payload = dict(row.budget_json or {})
        return ContextBudget(
            max_total_tokens=int(
                payload.get("max_total_tokens", default_budget.max_total_tokens)
            ),
            max_selected_artifacts=int(
                payload.get(
                    "max_selected_artifacts",
                    default_budget.max_selected_artifacts,
                )
            ),
            soft_max_total_tokens=payload.get(
                "soft_max_total_tokens",
                default_budget.soft_max_total_tokens,
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
            adaptive_trimming=str(
                payload.get("adaptive_trimming", default_budget.adaptive_trimming)
            ),
            lane_budgets=tuple(
                ContextLaneBudget(
                    lane=str(item.get("lane", "")).strip(),
                    min_items=int(item.get("min_items", 0)),
                    max_items=(
                        None
                        if item.get("max_items") in (None, "")
                        else int(item["max_items"])
                    ),
                    reserved_tokens=int(item.get("reserved_tokens", 0)),
                    allow_spillover=bool(item.get("allow_spillover", True)),
                )
                for item in payload.get("lane_budgets", ())
                if isinstance(item, dict) and str(item.get("lane", "")).strip() != ""
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
            commit_token_ttl_seconds=payload.get(
                "commit_token_ttl_seconds",
                default_policy.commit_token_ttl_seconds,
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
            commit_token_ttl_seconds=900,
        )
        if scope.tenant_id == str(GLOBAL_TENANT_ID):
            retention = ContextRetentionPolicy(
                allow_long_term_memory=True,
                require_partition_for_global_memory=True,
                cache_ttl_seconds=300,
                trace_ttl_seconds=86400,
                memory_ttl_seconds=None,
                commit_token_ttl_seconds=900,
            )
        return ContextPolicy(
            budget=ContextBudget(),
            redaction=ContextRedactionPolicy(
                redact_sensitive=True,
            ),
            retention=retention,
            trace_enabled=True,
            trace_capture_prepare=True,
            trace_capture_commit=True,
            trace_capture_selected=True,
            trace_capture_dropped=True,
            cache_enabled=True,
            metadata={"default_policy": True},
        )

    @staticmethod
    def _source_rule_from_binding(binding: ContextSourceBindingDE) -> ContextSourceRule:
        return ContextSourceRule(
            effect=ContextSourcePolicyEffect.ALLOW,
            kind=getattr(binding, "source_kind", None),
            source_key=getattr(binding, "source_key", None),
            locale=getattr(binding, "locale", None),
            category=getattr(binding, "category", None),
            metadata=dict(getattr(binding, "attributes", None) or {}),
        )

    @staticmethod
    def _merge_source_rules(
        *,
        binding_rules: tuple[ContextSourceRule, ...],
        allow_kinds: tuple[str, ...],
        deny_kinds: tuple[str, ...],
    ) -> tuple[ContextSourceRule, ...]:
        merged = list(binding_rules)
        merged.extend(
            ContextSourceRule(
                effect=ContextSourcePolicyEffect.ALLOW,
                kind=source_kind,
            )
            for source_kind in allow_kinds
        )
        merged.extend(
            ContextSourceRule(
                effect=ContextSourcePolicyEffect.DENY,
                kind=source_kind,
            )
            for source_kind in deny_kinds
        )
        return tuple(merged)

    @staticmethod
    def _dedupe_texts(values: tuple[str | None, ...]) -> tuple[str, ...]:
        deduped: list[str] = []
        for value in values:
            normalized = _normalize_optional_text(value)
            if normalized is None or normalized in deduped:
                continue
            deduped.append(normalized)
        return tuple(deduped)


def _serialize_source_ref(source: ContextSourceRef | None) -> dict[str, Any] | None:
    if source is None:
        return None
    return {
        "kind": source.kind,
        "source_key": source.source_key,
        "source_id": source.source_id,
        "canonical_locator": source.canonical_locator,
        "segment_id": source.segment_id,
        "locale": source.locale,
        "category": source.category,
        "metadata": dict(source.metadata),
    }


def _deserialize_source_ref(payload: object) -> ContextSourceRef | None:
    if not isinstance(payload, dict):
        return None
    source_kind = payload.get("kind")
    if not isinstance(source_kind, str) or source_kind.strip() == "":
        return None
    return ContextSourceRef(
        kind=source_kind,
        source_key=payload.get("source_key"),
        source_id=payload.get("source_id"),
        canonical_locator=payload.get("canonical_locator"),
        segment_id=payload.get("segment_id"),
        locale=payload.get("locale"),
        category=payload.get("category"),
        metadata=payload.get("metadata"),
    )


def _serialize_provenance(provenance: ContextProvenance) -> dict[str, Any]:
    return {
        "contributor": provenance.contributor,
        "source_kind": provenance.source_kind,
        "source_id": provenance.source_id,
        "source": _serialize_source_ref(provenance.source),
        "title": provenance.title,
        "uri": provenance.uri,
        "tenant_id": provenance.tenant_id,
        "trace_id": provenance.trace_id,
        "metadata": dict(provenance.metadata),
    }


def _deserialize_provenance(payload: object) -> ContextProvenance:
    data = dict(payload or {})
    return ContextProvenance(
        contributor=str(data.get("contributor") or "context_engine"),
        source_kind=str(data.get("source_kind") or "turn_commit"),
        source_id=_normalize_optional_text(data.get("source_id")),
        source=_deserialize_source_ref(data.get("source")),
        title=_normalize_optional_text(data.get("title")),
        uri=_normalize_optional_text(data.get("uri")),
        tenant_id=_normalize_optional_text(data.get("tenant_id")),
        trace_id=_normalize_optional_text(data.get("trace_id")),
        metadata=dict(data.get("metadata") or {}),
    )


def _serialize_memory_write(write: MemoryWrite) -> dict[str, Any]:
    return {
        "write_type": write.write_type.value,
        "content": write.content,
        "provenance": _serialize_provenance(write.provenance),
        "scope_partition": dict(write.scope_partition),
        "key": write.key,
        "subject": write.subject,
        "confidence": write.confidence,
        "ttl_seconds": write.ttl_seconds,
        "tags": list(write.tags),
        "metadata": dict(write.metadata),
    }


def _deserialize_memory_write(payload: object) -> MemoryWrite:
    data = dict(payload or {})
    write_type = data.get("write_type")
    if not isinstance(write_type, str):
        raise RuntimeError("Stored context commit result is missing write_type.")
    return MemoryWrite(
        write_type=MemoryWriteType(write_type),
        content=data.get("content"),
        provenance=_deserialize_provenance(data.get("provenance")),
        scope_partition=dict(data.get("scope_partition") or {}),
        key=_normalize_optional_text(data.get("key")),
        subject=_normalize_optional_text(data.get("subject")),
        confidence=data.get("confidence"),
        ttl_seconds=data.get("ttl_seconds"),
        tags=tuple(data.get("tags") or ()),
        metadata=dict(data.get("metadata") or {}),
    )


def _serialize_commit_result(result: ContextCommitResult) -> dict[str, Any]:
    return {
        "commit_token": result.commit_token,
        "state_revision": result.state_revision,
        "memory_writes": [
            _serialize_memory_write(write) for write in result.memory_writes
        ],
        "cache_updates": dict(result.cache_updates),
        "warnings": list(result.warnings),
    }


def _deserialize_commit_result(payload: object) -> ContextCommitResult:
    data = dict(payload or {})
    commit_token = data.get("commit_token")
    if not isinstance(commit_token, str) or commit_token.strip() == "":
        raise RuntimeError("Stored context commit result is missing commit_token.")
    return ContextCommitResult(
        commit_token=commit_token,
        state_revision=data.get("state_revision"),
        memory_writes=tuple(
            _deserialize_memory_write(write) for write in data.get("memory_writes", ())
        ),
        cache_updates=dict(data.get("cache_updates") or {}),
        warnings=tuple(data.get("warnings") or ()),
    )


def _trace_payload_for_policy(
    payload: dict[str, Any],
    *,
    policy: ContextPolicy,
) -> tuple[dict[str, Any], list[dict[str, Any]] | None, list[dict[str, Any]] | None]:
    normalized_payload = dict(payload)
    selected_items: list[dict[str, Any]] | None = None
    dropped_items: list[dict[str, Any]] | None = None

    selected_payload = normalized_payload.get("selected")
    if policy.trace_capture_selected is True and isinstance(selected_payload, list):
        selected_items = [
            dict(item) for item in selected_payload if isinstance(item, dict)
        ]
    else:
        normalized_payload.pop("selected", None)

    dropped_payload = normalized_payload.get("dropped")
    if policy.trace_capture_dropped is True and isinstance(dropped_payload, list):
        dropped_items = [
            dict(item) for item in dropped_payload if isinstance(item, dict)
        ]
    else:
        normalized_payload.pop("dropped", None)

    return normalized_payload, selected_items, dropped_items


class StructuredLaneRenderer(IContextArtifactRenderer):
    """Render one structured lane into a single system message."""

    def __init__(self, *, render_class: str, lane: str) -> None:
        self._render_class = render_class
        self._lane = lane

    @property
    def render_class(self) -> str:
        return self._render_class

    async def render(
        self,
        request: ContextTurnRequest,
        candidates: list[ContextCandidate],
        *,
        policy: ContextPolicy,
    ) -> list[CompletionMessage]:
        _ = request
        _ = policy
        if not candidates:
            return []
        items: list[dict[str, Any]] = []
        for candidate in candidates:
            if candidate.artifact.lane != self._lane:
                raise RuntimeError(
                    "StructuredLaneRenderer received unexpected lane "
                    f"{candidate.artifact.lane!r} "
                    f"for render_class={self._render_class!r}."
                )
            items.append(self._artifact_payload(candidate))
        return [
            CompletionMessage(
                role="system",
                content={
                    "context_lane": self._lane,
                    "render_class": self._render_class,
                    "items": items,
                },
            )
        ]

    @staticmethod
    def _artifact_payload(candidate: ContextCandidate) -> dict[str, Any]:
        artifact = candidate.artifact
        return {
            "artifact_id": artifact.artifact_id,
            "kind": artifact.kind,
            "title": artifact.title,
            "summary": artifact.summary,
            "content": artifact.content,
            "provenance": _serialize_provenance(artifact.provenance),
            "trust": artifact.trust,
            "freshness": artifact.freshness,
            "estimated_token_cost": artifact.estimated_token_cost,
            "metadata": dict(artifact.metadata),
        }


class RecentTurnMessageRenderer(IContextArtifactRenderer):
    """Render recent-turn artifacts into replayable completion messages."""

    render_class = "recent_turn_messages"

    async def render(
        self,
        request: ContextTurnRequest,
        candidates: list[ContextCandidate],
        *,
        policy: ContextPolicy,
    ) -> list[CompletionMessage]:
        _ = request
        _ = policy
        messages: list[CompletionMessage] = []
        for candidate in candidates:
            payload = candidate.artifact.content
            if not isinstance(payload, dict):
                raise RuntimeError("Recent-turn artifacts must have dict content.")
            role = payload.get("role")
            if not isinstance(role, str) or role.strip() == "":
                raise RuntimeError("Recent-turn artifacts must declare a string role.")
            content = payload.get("content")
            if content is not None and not isinstance(content, (str, dict, list)):
                raise RuntimeError(
                    "Recent-turn artifact content must be string, object, "
                    "list, or null."
                )
            messages.append(CompletionMessage(role=role, content=content))
        return messages


class RelationalContextCommitStore(IContextCommitStore):
    """Relational commit-token ledger with replay-safe duplicate handling."""

    def __init__(self, *, ledger_service: ContextCommitLedgerService) -> None:
        self._ledger_service = ledger_service

    async def issue_token(
        self,
        *,
        request: ContextTurnRequest,
        prepared_fingerprint: str,
        ttl_seconds: int | None = None,
    ) -> str:
        commit_token = f"ctxcmt_{uuid.uuid4().hex}"
        await self._ledger_service.create(
            {
                "tenant_id": _parse_tenant_uuid(request.scope.tenant_id),
                "scope_key": scope_key(request.scope),
                "commit_token": commit_token,
                "prepared_fingerprint": prepared_fingerprint,
                "commit_state": ContextCommitState.PREPARED.value,
                "expires_at": self._expires_at(ttl_seconds),
                "last_error": None,
                "result_json": None,
            }
        )
        return commit_token

    async def begin_commit(
        self,
        *,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
        prepared_fingerprint: str,
    ) -> ContextCommitCheck:
        row = await self._get_valid_row(
            request=request,
            prepared=prepared,
            prepared_fingerprint=prepared_fingerprint,
            allow_terminal_replay=True,
        )
        if row.commit_state == ContextCommitState.COMMITTED.value:
            if row.result_json is None:
                raise RuntimeError(
                    "Invalid context commit token: committed result missing."
                )
            return ContextCommitCheck(
                state=ContextCommitState.COMMITTED,
                replay_result=_deserialize_commit_result(row.result_json),
            )
        if row.commit_state == ContextCommitState.COMMITTING.value:
            raise RuntimeError(
                "Invalid context commit token: commit already in progress."
            )
        if row.commit_state == ContextCommitState.FAILED.value:
            raise RuntimeError("Invalid context commit token: previous commit failed.")

        updated = await self._update_row(
            row=row,
            changes={
                "commit_state": ContextCommitState.COMMITTING.value,
                "last_error": None,
            },
        )
        if updated is None:
            raise RuntimeError(
                "Invalid context commit token: commit transition failed."
            )
        return ContextCommitCheck(state=ContextCommitState.COMMITTING)

    async def complete_commit(
        self,
        *,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
        prepared_fingerprint: str,
        result: ContextCommitResult,
    ) -> None:
        row = await self._get_valid_row(
            request=request,
            prepared=prepared,
            prepared_fingerprint=prepared_fingerprint,
            allow_terminal_replay=False,
        )
        serialized_result = _serialize_commit_result(result)
        if row.commit_state == ContextCommitState.COMMITTED.value:
            if row.result_json == serialized_result:
                return
            raise RuntimeError("Invalid context commit token: already committed.")
        if row.commit_state != ContextCommitState.COMMITTING.value:
            raise RuntimeError("Invalid context commit token: commit not in progress.")
        updated = await self._update_row(
            row=row,
            changes={
                "commit_state": ContextCommitState.COMMITTED.value,
                "last_error": None,
                "result_json": serialized_result,
            },
        )
        if updated is None:
            raise RuntimeError("Invalid context commit token: commit finalize failed.")

    async def fail_commit(
        self,
        *,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
        prepared_fingerprint: str,
        error_message: str,
    ) -> None:
        row = await self._get_valid_row(
            request=request,
            prepared=prepared,
            prepared_fingerprint=prepared_fingerprint,
            allow_terminal_replay=True,
            raise_on_missing=False,
        )
        if row is None or row.commit_state == ContextCommitState.COMMITTED.value:
            return
        await self._update_row(
            row=row,
            changes={
                "commit_state": ContextCommitState.FAILED.value,
                "last_error": error_message[:1024],
            },
        )

    async def _get_valid_row(
        self,
        *,
        request: ContextTurnRequest,
        prepared: PreparedContextTurn,
        prepared_fingerprint: str,
        allow_terminal_replay: bool,
        raise_on_missing: bool = True,
    ) -> ContextCommitLedgerDE | None:
        tenant_id = _parse_tenant_uuid(request.scope.tenant_id)
        row = await self._ledger_service.get(
            {"tenant_id": tenant_id, "commit_token": prepared.commit_token}
        )
        if row is None:
            if raise_on_missing:
                raise RuntimeError("Invalid context commit token.")
            return None
        expected_scope_key = scope_key(request.scope)
        if _normalize_optional_text(row.scope_key) != expected_scope_key:
            raise RuntimeError("Invalid context commit token: scope mismatch.")
        if (
            prepared.state_handle is not None
            and prepared.state_handle != expected_scope_key
        ):
            raise RuntimeError("Invalid context commit token: prepared state mismatch.")
        if row.prepared_fingerprint != prepared_fingerprint:
            raise RuntimeError("Invalid context commit token: prepared mismatch.")
        if row.expires_at is not None and row.expires_at <= _utc_now():
            if row.commit_state != ContextCommitState.COMMITTED.value:
                await self._update_row(
                    row=row,
                    changes={
                        "commit_state": ContextCommitState.FAILED.value,
                        "last_error": "expired",
                    },
                )
                raise RuntimeError("Invalid context commit token: expired.")
            if not allow_terminal_replay:
                raise RuntimeError("Invalid context commit token: expired.")
        return row

    async def _update_row(
        self,
        *,
        row: ContextCommitLedgerDE,
        changes: dict[str, Any],
    ) -> ContextCommitLedgerDE | None:
        tenant_id = getattr(row, "tenant_id", None)
        if row.id is None or not isinstance(tenant_id, uuid.UUID):
            return None
        row_version = getattr(row, "row_version", None)
        if hasattr(self._ledger_service, "update_with_row_version") and isinstance(
            row_version, int
        ):
            return await self._ledger_service.update_with_row_version(
                {"tenant_id": tenant_id, "id": row.id},
                expected_row_version=row_version,
                changes=changes,
            )
        return await self._ledger_service.update(
            {"tenant_id": tenant_id, "id": row.id},
            changes,
        )

    @staticmethod
    def _expires_at(ttl_seconds: int | None) -> datetime | None:
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            return None
        return _utc_now().replace(microsecond=0) + timedelta(seconds=ttl_seconds)


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
        assistant_response = _assistant_text(
            completion=completion,
            final_user_responses=final_user_responses,
        )
        previous_payload = None
        next_state = None
        for _ in range(2):
            existing = await self._snapshot_service.get(
                {"tenant_id": tenant_id, "scope_key": scope_key_value}
            )
            previous_payload = (
                None
                if existing is None
                else self._snapshot_payload_from_row(
                    tenant_id=tenant_id,
                    row=existing,
                )
            )
            next_state = self._next_state(
                request=request,
                existing=existing,
                outcome=outcome,
            )
            payload = self._snapshot_payload(
                tenant_id=tenant_id,
                scope_key_value=scope_key_value,
                request=request,
                state=next_state,
            )
            try:
                await self._persist_snapshot(
                    tenant_id=tenant_id,
                    scope_key_value=scope_key_value,
                    existing=existing,
                    payload=payload,
                )
            except _StateSnapshotConflictError:
                continue
            break
        else:
            raise RuntimeError("Context state snapshot update conflict.")

        try:
            await self._append_turn_events(
                request=request,
                assistant_response=assistant_response,
                revision=next_state.revision,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            for rollback in (
                self._rollback_turn_events(
                    tenant_id=tenant_id,
                    scope_key_value=scope_key_value,
                    assistant_response=assistant_response,
                    revision=next_state.revision,
                ),
                self._rollback_snapshot(
                    tenant_id=tenant_id,
                    scope_key_value=scope_key_value,
                    request=request,
                    previous_payload=previous_payload,
                    failed_revision=next_state.revision,
                ),
            ):
                try:
                    await rollback
                except (
                    Exception
                ) as rollback_exc:  # pylint: disable=broad-exception-caught
                    exc.add_note(
                        "Context state rollback failed "
                        f"({type(rollback_exc).__name__}: {rollback_exc})."
                    )
            raise
        return next_state

    async def clear(self, request: ContextTurnRequest) -> None:
        tenant_id = _parse_tenant_uuid(request.scope.tenant_id)
        scope_key_value = scope_key(request.scope)
        await self._snapshot_service.delete(
            {"tenant_id": tenant_id, "scope_key": scope_key_value}
        )
        # The base service does not expose a bulk-delete helper.
        # pylint: disable=protected-access
        await self._event_log_service._rsg.delete_many(
            self._event_log_service.table,
            {
                "tenant_id": tenant_id,
                "scope_key": scope_key_value,
            },
        )

    async def _append_turn_events(
        self,
        *,
        request: ContextTurnRequest,
        assistant_response: str | None,
        revision: int,
    ) -> None:
        tenant_id = _parse_tenant_uuid(request.scope.tenant_id)
        scope_key_value = scope_key(request.scope)
        next_sequence = self._event_sequence_no(revision=revision)
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

    def _next_state(
        self,
        *,
        request: ContextTurnRequest,
        existing,
        outcome: TurnOutcome,
    ) -> ContextState:
        next_revision = int(0 if existing is None else existing.revision or 0) + 1
        return ContextState(
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
                "service_route_key": _request_service_route_key(request),
                "tenant_resolution": request.ingress_metadata.get("tenant_resolution"),
            },
            summary=None if existing is None else existing.summary,
            revision=next_revision,
            metadata={
                "message_id": request.message_id,
                "trace_id": request.trace_id,
                "outcome": outcome.value,
            },
        )

    @staticmethod
    def _snapshot_payload(
        *,
        tenant_id: uuid.UUID,
        scope_key_value: str,
        request: ContextTurnRequest,
        state: ContextState,
    ) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "scope_key": scope_key_value,
            "platform": request.scope.platform,
            "channel_id": request.scope.channel_id,
            "room_id": request.scope.room_id,
            "sender_id": request.scope.sender_id,
            "conversation_id": request.scope.conversation_id,
            "case_id": request.scope.case_id,
            "workflow_id": request.scope.workflow_id,
            "current_objective": state.current_objective,
            "entities": state.entities,
            "constraints": state.constraints,
            "unresolved_slots": state.unresolved_slots,
            "commitments": state.commitments,
            "safety_flags": state.safety_flags,
            "routing": state.routing,
            "summary": state.summary,
            "revision": state.revision,
            "last_message_id": request.message_id,
            "last_trace_id": request.trace_id,
            "attributes": state.metadata,
        }

    @staticmethod
    def _snapshot_payload_from_row(
        *,
        tenant_id: uuid.UUID,
        row,
    ) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "scope_key": row.scope_key,
            "platform": getattr(row, "platform", None),
            "channel_id": getattr(row, "channel_id", None),
            "room_id": getattr(row, "room_id", None),
            "sender_id": getattr(row, "sender_id", None),
            "conversation_id": getattr(row, "conversation_id", None),
            "case_id": getattr(row, "case_id", None),
            "workflow_id": getattr(row, "workflow_id", None),
            "current_objective": getattr(row, "current_objective", None),
            "entities": dict(getattr(row, "entities", None) or {}),
            "constraints": list(getattr(row, "constraints", None) or []),
            "unresolved_slots": list(getattr(row, "unresolved_slots", None) or []),
            "commitments": list(getattr(row, "commitments", None) or []),
            "safety_flags": list(getattr(row, "safety_flags", None) or []),
            "routing": dict(getattr(row, "routing", None) or {}),
            "summary": getattr(row, "summary", None),
            "revision": int(getattr(row, "revision", None) or 0),
            "last_message_id": getattr(row, "last_message_id", None),
            "last_trace_id": getattr(row, "last_trace_id", None),
            "attributes": dict(getattr(row, "attributes", None) or {}),
        }

    async def _persist_snapshot(
        self,
        *,
        tenant_id: uuid.UUID,
        scope_key_value: str,
        existing,
        payload: dict[str, Any],
    ):
        if existing is None or existing.id is None:
            try:
                return await self._snapshot_service.create(payload)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                latest = await self._snapshot_service.get(
                    {"tenant_id": tenant_id, "scope_key": scope_key_value}
                )
                if latest is not None:
                    raise _StateSnapshotConflictError(
                        "Context state snapshot create conflict."
                    ) from exc
                raise

        updated = await self._update_snapshot_row(
            tenant_id=tenant_id,
            row=existing,
            payload=payload,
        )
        if updated is None:
            raise _StateSnapshotConflictError(
                "Context state snapshot update conflict."
            )
        return updated

    async def _update_snapshot_row(
        self,
        *,
        tenant_id: uuid.UUID,
        row,
        payload: dict[str, Any],
    ):
        updater = getattr(self._snapshot_service, "update_with_row_version", None)
        row_version = getattr(row, "row_version", None)
        if callable(updater) and isinstance(row_version, int):
            return await updater(
                {"tenant_id": tenant_id, "id": row.id},
                expected_row_version=row_version,
                changes=payload,
            )
        return await self._snapshot_service.update(
            {"tenant_id": tenant_id, "id": row.id},
            payload,
        )

    async def _rollback_snapshot(
        self,
        *,
        tenant_id: uuid.UUID,
        scope_key_value: str,
        request: ContextTurnRequest,
        previous_payload: dict[str, Any] | None,
        failed_revision: int,
    ) -> None:
        current = await self._snapshot_service.get(
            {"tenant_id": tenant_id, "scope_key": scope_key_value}
        )
        if current is None or current.id is None:
            return
        if int(getattr(current, "revision", 0) or 0) != failed_revision:
            return
        if getattr(current, "last_message_id", None) != request.message_id:
            return
        if getattr(current, "last_trace_id", None) != request.trace_id:
            return

        if previous_payload is None:
            deleter = getattr(self._snapshot_service, "delete_with_row_version", None)
            row_version = getattr(current, "row_version", None)
            if callable(deleter) and isinstance(row_version, int):
                await deleter(
                    {"tenant_id": tenant_id, "id": current.id},
                    expected_row_version=row_version,
                )
                return
            await self._snapshot_service.delete(
                {"tenant_id": tenant_id, "id": current.id}
            )
            return

        updated = await self._update_snapshot_row(
            tenant_id=tenant_id,
            row=current,
            payload=previous_payload,
        )
        if updated is None:
            raise RuntimeError("Context state snapshot rollback conflict.")

    async def _rollback_turn_events(
        self,
        *,
        tenant_id: uuid.UUID,
        scope_key_value: str,
        assistant_response: str | None,
        revision: int,
    ) -> None:
        deleter = getattr(self._event_log_service, "delete", None)
        if callable(deleter) is not True:
            return
        sequence_nos = [self._event_sequence_no(revision=revision)]
        if assistant_response is not None:
            sequence_nos.append(sequence_nos[0] + 1)
        for sequence_no in reversed(sequence_nos):
            await deleter(
                {
                    "tenant_id": tenant_id,
                    "scope_key": scope_key_value,
                    "sequence_no": sequence_no,
                }
            )

    @staticmethod
    def _event_sequence_no(*, revision: int) -> int:
        return max(((int(revision) - 1) * 2) + 1, 1)

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
            expires_at = _utc_now().replace(microsecond=0) + timedelta(
                seconds=ttl_seconds
            )
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
        policy = prepared.bundle.policy
        if not policy.trace_enabled:
            return
        payload, selected_items, dropped_items = _trace_payload_for_policy(
            dict(prepared.trace),
            policy=policy,
        )
        await self._persist_trace(
            request=request,
            stage="prepare",
            payload=payload,
            selected_items=selected_items,
            dropped_items=dropped_items,
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
        policy = prepared.bundle.policy
        if not policy.trace_enabled:
            return
        payload = {
            "completion_model": None if completion is None else completion.model,
            "completion_stop_reason": (
                None if completion is None else completion.stop_reason
            ),
            "final_user_responses": final_user_responses,
            "outcome": outcome.value,
            "commit_result": _serialize_commit_result(result),
        }
        _, selected_items, dropped_items = _trace_payload_for_policy(
            dict(prepared.trace),
            policy=policy,
        )
        await self._persist_trace(
            request=request,
            stage="commit",
            payload=payload,
            selected_items=selected_items,
            dropped_items=dropped_items,
        )

    async def _persist_trace(
        self,
        *,
        request: ContextTurnRequest,
        stage: str,
        payload: dict[str, Any],
        selected_items: list[dict[str, Any]] | None,
        dropped_items: list[dict[str, Any]] | None,
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
        provenance = (
            prepared.bundle.selected_candidates[0].artifact.provenance
            if (prepared.bundle.selected_candidates)
            else None
        )
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
    ) -> ContextGuardResult:
        _ = state
        allowed = set(policy.redaction.allowed_sensitivity_labels)
        blocked = set(policy.redaction.blocked_sensitivity_labels).difference(allowed)
        guarded: list[ContextCandidate] = []
        dropped: list[ContextCandidate] = []
        for candidate in candidates:
            provenance_tenant = candidate.artifact.provenance.tenant_id
            if (
                provenance_tenant is not None
                and provenance_tenant != request.scope.tenant_id
            ):
                dropped.append(
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
                dropped.append(
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
                dropped.append(
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
        return ContextGuardResult(
            passed_candidates=tuple(guarded),
            dropped_candidates=tuple(dropped),
        )


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

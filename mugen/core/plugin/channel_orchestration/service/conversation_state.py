"""Provides orchestration actions for conversation state transitions."""

__all__ = ["ConversationStateService"]

from datetime import datetime, timedelta, timezone
import uuid

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.channel_orchestration.api.validation import (
    ApplyThrottleValidation,
    EscalateConversationValidation,
    EvaluateIntakeValidation,
    RouteConversationValidation,
    SetFallbackValidation,
)
from mugen.core.plugin.channel_orchestration.domain import (
    BlocklistEntryDE,
    ConversationStateDE,
    IntakeRuleDE,
    OrchestrationPolicyDE,
    RoutingRuleDE,
    ThrottleRuleDE,
)
from mugen.core.plugin.channel_orchestration.service.blocklist_entry import (
    BlocklistEntryService,
)
from mugen.core.plugin.channel_orchestration.service.orchestration_event import (
    OrchestrationEventService,
)
from mugen.core.plugin.channel_orchestration.service.orchestration_policy import (
    OrchestrationPolicyService,
)
from ..contract.service.conversation_state import IConversationStateService
from .intake_rule import IntakeRuleService
from .routing_rule import RoutingRuleService
from .throttle_rule import ThrottleRuleService


class ConversationStateService(
    IRelationalService[ConversationStateDE],
    IConversationStateService,
):
    """A CRUD/action service for channel orchestration conversation state."""

    _INTAKE_RULE_TABLE = "channel_orchestration_intake_rule"
    _ROUTING_RULE_TABLE = "channel_orchestration_routing_rule"
    _POLICY_TABLE = "channel_orchestration_orchestration_policy"
    _THROTTLE_RULE_TABLE = "channel_orchestration_throttle_rule"
    _BLOCKLIST_TABLE = "channel_orchestration_blocklist_entry"
    _EVENT_TABLE = "channel_orchestration_orchestration_event"

    _MATCH_KIND_RANK: dict[str, int] = {
        "intent": 3,
        "keyword": 2,
        "menu": 1,
    }

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=ConversationStateDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

        self._intake_rule_service = IntakeRuleService(
            table=self._INTAKE_RULE_TABLE,
            rsg=rsg,
        )
        self._routing_rule_service = RoutingRuleService(
            table=self._ROUTING_RULE_TABLE,
            rsg=rsg,
        )
        self._policy_service = OrchestrationPolicyService(
            table=self._POLICY_TABLE,
            rsg=rsg,
        )
        self._throttle_rule_service = ThrottleRuleService(
            table=self._THROTTLE_RULE_TABLE,
            rsg=rsg,
        )
        self._blocklist_service = BlocklistEntryService(
            table=self._BLOCKLIST_TABLE,
            rsg=rsg,
        )
        self._event_service = OrchestrationEventService(
            table=self._EVENT_TABLE,
            rsg=rsg,
        )

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None

        clean = str(value).strip()
        return clean or None

    @staticmethod
    def _normalized_casefold(value: str | None) -> str | None:
        text = ConversationStateService._normalize_optional_text(value)
        return text.casefold() if text else None

    @classmethod
    def _kind_rank(cls, match_kind: str | None) -> int:
        return cls._MATCH_KIND_RANK.get((match_kind or "").strip().lower(), 0)

    @staticmethod
    def _rule_timestamp(rule: IntakeRuleDE) -> float:
        if rule.created_at is None:
            return 0.0

        created = rule.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return created.timestamp()

    @classmethod
    def _rule_sort_key(cls, rule: IntakeRuleDE) -> tuple[int, int, float]:
        return (
            cls._kind_rank(rule.match_kind),
            int(rule.priority or 0),
            cls._rule_timestamp(rule),
        )

    @staticmethod
    def _rule_matches(rule: IntakeRuleDE, data: EvaluateIntakeValidation) -> bool:
        match_kind = (rule.match_kind or "").strip().lower()
        rule_values = [
            part.strip().casefold()
            for part in str(rule.match_value or "").split(",")
            if part.strip()
        ]
        if not rule_values:
            return False

        if match_kind == "intent":
            value = ConversationStateService._normalized_casefold(data.intent)
        elif match_kind == "keyword":
            value = ConversationStateService._normalized_casefold(data.keyword)
        elif match_kind == "menu":
            value = ConversationStateService._normalized_casefold(data.menu_option)
        else:
            return False

        if value is None:
            return False

        return value in rule_values

    async def _get_for_action(
        self,
        *,
        where: dict,
        expected_row_version: int,
    ) -> ConversationStateDE:
        where_with_version = dict(where)
        where_with_version["row_version"] = expected_row_version

        try:
            current = await self.get(where_with_version)
        except SQLAlchemyError:
            abort(500)

        if current is not None:
            return current

        try:
            base = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if base is None:
            abort(404, "Conversation state not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_with_row_version(
        self,
        *,
        where: dict,
        expected_row_version: int,
        changes: dict,
    ) -> ConversationStateDE:
        svc: ICrudServiceWithRowVersion[ConversationStateDE] = self

        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes=changes,
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return updated

    async def _append_event(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_state_id: uuid.UUID,
        channel_profile_id: uuid.UUID | None,
        sender_key: str | None,
        event_type: str,
        decision: str | None,
        reason: str | None,
        actor_user_id: uuid.UUID,
        payload: dict | None = None,
    ) -> None:
        await self._event_service.create(
            {
                "tenant_id": tenant_id,
                "conversation_state_id": conversation_state_id,
                "channel_profile_id": channel_profile_id,
                "sender_key": self._normalize_optional_text(sender_key),
                "event_type": event_type,
                "decision": self._normalize_optional_text(decision),
                "reason": self._normalize_optional_text(reason),
                "payload": payload,
                "actor_user_id": actor_user_id,
                "occurred_at": self._now_utc(),
                "source": "channel_orchestration",
            }
        )

    async def _active_blocklist_entry(
        self,
        *,
        tenant_id: uuid.UUID,
        sender_key: str,
        channel_profile_id: uuid.UUID | None,
    ) -> BlocklistEntryDE | None:
        now = self._now_utc()
        rows = await self._blocklist_service.list()

        for row in rows:
            if row.tenant_id != tenant_id:
                continue

            if not bool(row.is_active):
                continue

            if (row.sender_key or "").casefold() != sender_key.casefold():
                continue

            if row.channel_profile_id not in (None, channel_profile_id):
                continue

            if row.expires_at is not None and row.expires_at <= now:
                continue

            return row

        return None

    async def _candidate_intake_rules(
        self,
        *,
        tenant_id: uuid.UUID,
        channel_profile_id: uuid.UUID | None,
    ) -> list[IntakeRuleDE]:
        rows = await self._intake_rule_service.list()
        return [
            row
            for row in rows
            if row.tenant_id == tenant_id
            and bool(row.is_active)
            and row.channel_profile_id in (None, channel_profile_id)
        ]

    async def _resolve_policy(
        self,
        *,
        tenant_id: uuid.UUID,
        policy_id: uuid.UUID | None,
    ) -> OrchestrationPolicyDE | None:
        if policy_id is None:
            return None

        return await self._policy_service.get({"tenant_id": tenant_id, "id": policy_id})

    async def _resolve_routing_rule(
        self,
        *,
        tenant_id: uuid.UUID,
        channel_profile_id: uuid.UUID | None,
        route_key: str | None,
    ) -> RoutingRuleDE | None:
        rows = await self._routing_rule_service.list()
        candidates = [
            row
            for row in rows
            if row.tenant_id == tenant_id
            and bool(row.is_active)
            and row.channel_profile_id in (None, channel_profile_id)
        ]

        normalized_key = self._normalized_casefold(route_key)
        if normalized_key is not None:
            candidates = [
                row
                for row in candidates
                if self._normalized_casefold(row.route_key) == normalized_key
            ]

        if not candidates:
            return None

        candidates.sort(key=lambda row: int(row.priority or 0), reverse=True)
        return candidates[0]

    async def _resolve_throttle_rule(
        self,
        *,
        tenant_id: uuid.UUID,
        channel_profile_id: uuid.UUID | None,
    ) -> ThrottleRuleDE | None:
        rows = await self._throttle_rule_service.list()
        candidates = [
            row
            for row in rows
            if row.tenant_id == tenant_id
            and bool(row.is_active)
            and row.channel_profile_id in (None, channel_profile_id)
        ]

        if not candidates:
            return None

        candidates.sort(key=lambda row: int(row.priority or 0), reverse=True)
        return candidates[0]

    async def _upsert_blocklist_entry(
        self,
        *,
        tenant_id: uuid.UUID,
        channel_profile_id: uuid.UUID | None,
        sender_key: str,
        reason: str,
        actor_user_id: uuid.UUID,
        expires_at: datetime | None,
    ) -> None:
        existing = await self._active_blocklist_entry(
            tenant_id=tenant_id,
            sender_key=sender_key,
            channel_profile_id=channel_profile_id,
        )

        now = self._now_utc()
        if existing is None:
            await self._blocklist_service.create(
                {
                    "tenant_id": tenant_id,
                    "channel_profile_id": channel_profile_id,
                    "sender_key": sender_key,
                    "reason": reason,
                    "blocked_at": now,
                    "blocked_by_user_id": actor_user_id,
                    "expires_at": expires_at,
                    "is_active": True,
                }
            )
            return

        await self._blocklist_service.update(
            {
                "tenant_id": tenant_id,
                "id": existing.id,
            },
            {
                "reason": reason,
                "blocked_at": now,
                "blocked_by_user_id": actor_user_id,
                "expires_at": expires_at,
                "is_active": True,
                "unblocked_at": None,
                "unblocked_by_user_id": None,
                "unblock_reason": None,
            },
        )

    async def action_evaluate_intake(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: EvaluateIntakeValidation,
    ) -> tuple[dict[str, str | None], int]:
        """Evaluate intake rule precedence and set intake decision state."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        sender_key = self._normalize_optional_text(current.sender_key)
        if sender_key is None:
            abort(409, "Conversation state sender is not set.")

        now = self._now_utc()

        blocked = await self._active_blocklist_entry(
            tenant_id=tenant_id,
            sender_key=sender_key,
            channel_profile_id=current.channel_profile_id,
        )
        if blocked is not None:
            await self._update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes={
                    "status": "blocked",
                    "is_throttled": True,
                    "last_intake_result": "blocked",
                    "last_activity_at": now,
                },
            )
            await self._append_event(
                tenant_id=tenant_id,
                conversation_state_id=entity_id,
                channel_profile_id=current.channel_profile_id,
                sender_key=sender_key,
                event_type="evaluate_intake",
                decision="blocked",
                reason="sender is blocklisted",
                actor_user_id=auth_user_id,
                payload={
                    "blocklist_entry_id": str(blocked.id),
                },
            )
            return {
                "Decision": "blocked",
                "IntakeRuleId": None,
            }, 200

        candidates = await self._candidate_intake_rules(
            tenant_id=tenant_id,
            channel_profile_id=current.channel_profile_id,
        )
        matched = [rule for rule in candidates if self._rule_matches(rule, data)]
        matched.sort(key=self._rule_sort_key, reverse=True)

        selected = matched[0] if matched else None
        decision = "matched" if selected is not None else "no_match"

        changes = {
            "status": "intake_matched" if selected is not None else "awaiting_route",
            "last_intake_rule_id": selected.id if selected is not None else None,
            "last_intake_result": decision,
            "last_activity_at": now,
        }
        if selected is not None and self._normalize_optional_text(selected.route_key):
            changes["route_key"] = selected.route_key

        await self._update_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes=changes,
        )

        await self._append_event(
            tenant_id=tenant_id,
            conversation_state_id=entity_id,
            channel_profile_id=current.channel_profile_id,
            sender_key=sender_key,
            event_type="evaluate_intake",
            decision=decision,
            reason="rule_evaluation",
            actor_user_id=auth_user_id,
            payload={
                "intake_rule_id": str(selected.id) if selected is not None else None,
            },
        )

        return {
            "Decision": decision,
            "IntakeRuleId": str(selected.id) if selected is not None else None,
        }, 200

    async def action_route(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: RouteConversationValidation,
    ) -> tuple[dict[str, str | None], int]:
        """Resolve route assignment from routing rules and fallback policy."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        now = self._now_utc()
        route_key = self._normalize_optional_text(
            data.route_key
        ) or self._normalize_optional_text(current.route_key)

        routing_rule = await self._resolve_routing_rule(
            tenant_id=tenant_id,
            channel_profile_id=current.channel_profile_id,
            route_key=route_key,
        )

        policy = await self._resolve_policy(
            tenant_id=tenant_id,
            policy_id=current.policy_id,
        )

        fallback_mode = self._normalize_optional_text(current.fallback_mode)
        fallback_target = self._normalize_optional_text(current.fallback_target)
        if policy is not None:
            fallback_mode = fallback_mode or self._normalize_optional_text(
                policy.fallback_policy
            )
            fallback_target = fallback_target or self._normalize_optional_text(
                policy.fallback_target
            )

        if routing_rule is not None:
            queue_name = self._normalize_optional_text(
                data.queue_name
            ) or self._normalize_optional_text(routing_rule.target_queue_name)
            service_key = self._normalize_optional_text(
                data.service_key
            ) or self._normalize_optional_text(routing_rule.target_service_key)
            owner_user_id = data.owner_user_id or routing_rule.owner_user_id

            changes = {
                "status": "routed",
                "route_key": self._normalize_optional_text(routing_rule.route_key),
                "assigned_queue_name": queue_name,
                "assigned_service_key": service_key,
                "assigned_owner_user_id": owner_user_id,
                "is_fallback_active": False,
                "last_activity_at": now,
            }
            decision = "routed"
            reason = "routing_rule"
        else:
            fallback_queue = self._normalize_optional_text(
                data.queue_name
            ) or fallback_target
            changes = {
                "status": "fallback",
                "route_key": fallback_queue or route_key,
                "assigned_queue_name": fallback_queue,
                "fallback_mode": fallback_mode,
                "fallback_target": fallback_target,
                "is_fallback_active": True,
                "last_activity_at": now,
            }
            decision = "fallback"
            reason = "fallback_policy"

        await self._update_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes=changes,
        )

        await self._append_event(
            tenant_id=tenant_id,
            conversation_state_id=entity_id,
            channel_profile_id=current.channel_profile_id,
            sender_key=current.sender_key,
            event_type="route",
            decision=decision,
            reason=reason,
            actor_user_id=auth_user_id,
            payload={
                "route_key": changes.get("route_key"),
                "queue_name": changes.get("assigned_queue_name"),
                "service_key": changes.get("assigned_service_key"),
            },
        )

        return {
            "Decision": decision,
            "RouteKey": changes.get("route_key"),
            "QueueName": changes.get("assigned_queue_name"),
        }, 200

    async def action_escalate(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: EscalateConversationValidation,
    ) -> tuple[dict[str, str], int]:
        """Escalate conversation state according to policy defaults."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        now = self._now_utc()
        level = int(data.escalation_level or ((current.escalation_level or 0) + 1))

        policy = await self._resolve_policy(
            tenant_id=tenant_id,
            policy_id=current.policy_id,
        )

        changes = {
            "status": "escalated",
            "escalation_level": level,
            "is_escalated": True,
            "last_activity_at": now,
        }

        escalation_target = None
        if policy is not None:
            escalation_target = self._normalize_optional_text(policy.escalation_target)

        if escalation_target is not None:
            changes["route_key"] = escalation_target

        await self._update_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes=changes,
        )

        await self._append_event(
            tenant_id=tenant_id,
            conversation_state_id=entity_id,
            channel_profile_id=current.channel_profile_id,
            sender_key=current.sender_key,
            event_type="escalate",
            decision="escalated",
            reason=self._normalize_optional_text(data.reason),
            actor_user_id=auth_user_id,
            payload={
                "escalation_level": level,
                "escalation_target": escalation_target,
            },
        )

        return {"Decision": "escalated"}, 200

    async def action_apply_throttle(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: ApplyThrottleValidation,
    ) -> tuple[dict[str, str | int], int]:
        """Apply throttle rule and optionally add sender to blocklist."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        sender_key = self._normalize_optional_text(current.sender_key)
        if sender_key is None:
            abort(409, "Conversation state sender is not set.")

        now = self._now_utc()
        rule = await self._resolve_throttle_rule(
            tenant_id=tenant_id,
            channel_profile_id=current.channel_profile_id,
        )

        if rule is None:
            await self._append_event(
                tenant_id=tenant_id,
                conversation_state_id=entity_id,
                channel_profile_id=current.channel_profile_id,
                sender_key=sender_key,
                event_type="apply_throttle",
                decision="allowed",
                reason="no_active_throttle_rule",
                actor_user_id=auth_user_id,
            )
            return {
                "Decision": "allowed",
                "WindowCount": int(current.window_message_count or 0),
            }, 200

        window_seconds = max(1, int(rule.window_seconds or 60))
        max_messages = max(1, int(rule.max_messages or 1))

        started_at = current.window_started_at or now
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        if (now - started_at).total_seconds() >= window_seconds:
            started_at = now
            count = 0
        else:
            count = int(current.window_message_count or 0)

        count += int(data.increment_count)
        is_throttled = count > max_messages

        throttle_until = None
        if is_throttled:
            duration = int(rule.block_duration_seconds or window_seconds)
            if duration > 0:
                throttle_until = now + timedelta(seconds=duration)

        changes = {
            "window_started_at": started_at,
            "window_message_count": count,
            "is_throttled": is_throttled,
            "throttled_until": throttle_until,
            "status": "throttled" if is_throttled else "routed",
            "last_activity_at": now,
        }

        await self._update_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes=changes,
        )

        if is_throttled and bool(rule.block_on_violation):
            await self._upsert_blocklist_entry(
                tenant_id=tenant_id,
                channel_profile_id=current.channel_profile_id,
                sender_key=sender_key,
                reason="throttle_violation",
                actor_user_id=auth_user_id,
                expires_at=throttle_until,
            )

        await self._append_event(
            tenant_id=tenant_id,
            conversation_state_id=entity_id,
            channel_profile_id=current.channel_profile_id,
            sender_key=sender_key,
            event_type="apply_throttle",
            decision="throttled" if is_throttled else "allowed",
            reason="rule_evaluation",
            actor_user_id=auth_user_id,
            payload={
                "window_seconds": window_seconds,
                "max_messages": max_messages,
                "window_count": count,
            },
        )

        return {
            "Decision": "throttled" if is_throttled else "allowed",
            "WindowCount": count,
        }, 200

    async def action_set_fallback(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: SetFallbackValidation,
    ) -> tuple[dict[str, str], int]:
        """Set fallback mode/target for conversation routing."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        now = self._now_utc()
        fallback_mode = self._normalize_optional_text(data.fallback_mode)
        if fallback_mode is None:
            abort(400, "FallbackMode must be non-empty.")

        fallback_target = self._normalize_optional_text(data.fallback_target)
        fallback_reason = self._normalize_optional_text(data.reason)

        await self._update_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "fallback_mode": fallback_mode,
                "fallback_target": fallback_target,
                "fallback_reason": fallback_reason,
                "is_fallback_active": True,
                "status": "fallback_configured",
                "last_activity_at": now,
            },
        )

        await self._append_event(
            tenant_id=tenant_id,
            conversation_state_id=entity_id,
            channel_profile_id=current.channel_profile_id,
            sender_key=current.sender_key,
            event_type="set_fallback",
            decision="configured",
            reason=fallback_reason,
            actor_user_id=auth_user_id,
            payload={
                "fallback_mode": fallback_mode,
                "fallback_target": fallback_target,
            },
        )

        return {"Decision": "configured"}, 200

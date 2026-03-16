"""Provides a CRUD service for policy definitions and evaluation actions."""

__all__ = ["PolicyDefinitionService"]

from datetime import datetime, timezone
import uuid
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.ops_governance.api.validation import (
    ActivatePolicyVersionActionValidation,
    EvaluatePolicyActionValidation,
)
from mugen.core.plugin.ops_governance.contract.service.policy_definition import (
    IPolicyDefinitionService,
)
from mugen.core.plugin.ops_governance.domain import PolicyDefinitionDE
from mugen.core.plugin.ops_governance.service.policy_decision_log import (
    PolicyDecisionLogService,
)


class PolicyDefinitionService(
    IRelationalService[PolicyDefinitionDE],
    IPolicyDefinitionService,
):
    """A CRUD service for policy definitions and evaluation events."""

    _DECISION_LOG_TABLE = "ops_governance_policy_decision_log"
    _DECISION_SET = {"allow", "deny", "warn", "review"}
    _OUTCOME_SET = {"applied", "blocked", "deferred"}
    _OUTCOME_BY_DECISION = {
        "allow": "applied",
        "warn": "applied",
        "review": "deferred",
        "deny": "blocked",
    }

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=PolicyDefinitionDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._decision_log_service = PolicyDecisionLogService(
            table=self._DECISION_LOG_TABLE,
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
    def _normalize_required_text(value: str, *, field_name: str) -> str:
        clean = str(value).strip().lower()
        if not clean:
            abort(400, f"{field_name} must be non-empty.")
        return clean

    @classmethod
    def _normalize_decision(cls, value: str) -> str:
        clean = cls._normalize_required_text(value, field_name="Decision")
        if clean not in cls._DECISION_SET:
            abort(400, "Decision must be one of: allow, deny, warn, review.")
        return clean

    @classmethod
    def _normalize_outcome(cls, value: str) -> str:
        clean = cls._normalize_required_text(value, field_name="Outcome")
        if clean not in cls._OUTCOME_SET:
            abort(400, "Outcome must be one of: applied, blocked, deferred.")
        return clean

    @classmethod
    def _as_mapping(cls, value: Any, *, field_name: str) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            abort(409, f"{field_name} must be an object.")
        return dict(value)

    @classmethod
    def _event_get(cls, payload: Mapping[str, Any], key: str) -> Any:
        direct = payload.get(key)
        if direct is not None:
            return direct

        key_lower = key.lower()
        for candidate_key, candidate_value in payload.items():
            if str(candidate_key).lower() == key_lower:
                return candidate_value
        return None

    @classmethod
    def _extract_path(cls, payload: Mapping[str, Any], path: str) -> Any:
        cursor: Any = payload
        for part in path.split("."):
            clean_part = cls._normalize_optional_text(part)
            if clean_part is None:
                return None
            if not isinstance(cursor, Mapping):
                return None
            cursor = cls._event_get(cursor, clean_part)
            if cursor is None:
                return None
        return cursor

    @staticmethod
    def _compare(op: str, actual: Any, expected: Any) -> bool:
        clean_op = (op or "eq").strip().lower()
        if clean_op == "ne":
            return actual != expected
        if clean_op == "in":
            if not isinstance(expected, list):
                return False
            return actual in expected
        if clean_op == "contains":
            if isinstance(actual, str) and isinstance(expected, str):
                return expected in actual
            if isinstance(actual, list):
                return expected in actual
            return False
        return actual == expected

    @classmethod
    def _matches_condition(cls, payload: Mapping[str, Any], condition: Any) -> bool:
        if not isinstance(condition, Mapping):
            return False

        any_rules = condition.get("Any")
        if isinstance(any_rules, list) and any_rules:
            return any(cls._matches_condition(payload, item) for item in any_rules)

        all_rules = condition.get("All")
        if isinstance(all_rules, list) and all_rules:
            return all(cls._matches_condition(payload, item) for item in all_rules)

        path = cls._normalize_optional_text(condition.get("Path"))
        if path is not None:
            expected = condition.get("Value")
            op = str(condition.get("Op") or "eq")
            actual = cls._extract_path(payload, path)
            return cls._compare(op, actual, expected)

        for key, expected in condition.items():
            if str(key) in {"Any", "All", "Path", "Op", "Value"}:
                continue
            actual = cls._event_get(payload, str(key))
            if actual != expected:
                return False

        return True

    @classmethod
    def _rule_reasons(cls, rule: Mapping[str, Any]) -> list[str]:
        reasons: list[str] = []
        reason = cls._normalize_optional_text(
            rule.get("Reason") if isinstance(rule.get("Reason"), str) else None
        )
        if reason is not None:
            reasons.append(reason)

        raw_reasons = rule.get("Reasons")
        if isinstance(raw_reasons, list):
            for item in raw_reasons:
                if not isinstance(item, str):
                    continue
                clean = cls._normalize_optional_text(item)
                if clean is not None:
                    reasons.append(clean)

        deduped: list[str] = []
        for reason_item in reasons:
            if reason_item not in deduped:
                deduped.append(reason_item)
        return deduped

    @staticmethod
    def _rule_obligations(rule: Mapping[str, Any]) -> list[Any]:
        raw = rule.get("Obligations")
        if not isinstance(raw, list):
            return []
        obligations: list[Any] = []
        for item in raw:
            if isinstance(item, Mapping):
                obligations.append(dict(item))
                continue
            obligations.append(item)
        return obligations

    @classmethod
    def _rule_decision(
        cls,
        rule: Any,
        *,
        fallback: str | None = None,
    ) -> str:
        raw = None
        if isinstance(rule, Mapping):
            raw = rule.get("Effect") or rule.get("Decision")
        else:
            raw = rule

        if raw is None:
            if fallback is None:
                raise ValueError("Rule/Default decision is missing.")
            return fallback

        clean = str(raw).strip().lower()
        if clean not in cls._DECISION_SET:
            raise ValueError(
                "Policy document decision/effect must be one of: "
                "allow, deny, warn, review."
            )
        return clean

    @classmethod
    def _evaluate_document(
        cls,
        *,
        document: Mapping[str, Any],
        input_json: Mapping[str, Any],
    ) -> dict[str, Any]:
        raw_rules = document.get("Rules")
        rules = raw_rules if isinstance(raw_rules, list) else []

        matched_rule: Mapping[str, Any] | None = None
        for raw_rule in rules:
            if not isinstance(raw_rule, Mapping):
                continue
            condition = raw_rule.get("Condition")
            if condition is None:
                condition = raw_rule.get("When")
            if condition is None:
                condition = raw_rule.get("Match")

            if condition is not None and not cls._matches_condition(
                input_json,
                condition,
            ):
                continue

            matched_rule = raw_rule
            break

        if matched_rule is not None:
            decision = cls._rule_decision(matched_rule)
            reasons = cls._rule_reasons(matched_rule)
            obligations = cls._rule_obligations(matched_rule)
            return {
                "decision": decision,
                "reasons": reasons,
                "obligations": obligations,
                "matched_rule": cls._normalize_optional_text(
                    (
                        matched_rule.get("Key")
                        if isinstance(matched_rule.get("Key"), str)
                        else matched_rule.get("Name")
                        if isinstance(matched_rule.get("Name"), str)
                        else None
                    )
                ),
            }

        raw_default = document.get("Default")
        if raw_default is None:
            return {
                "decision": "deny",
                "reasons": ["no matching rule and no default decision"],
                "obligations": [],
                "matched_rule": None,
            }

        default_decision = cls._rule_decision(raw_default, fallback="deny")
        if isinstance(raw_default, Mapping):
            return {
                "decision": default_decision,
                "reasons": cls._rule_reasons(raw_default),
                "obligations": cls._rule_obligations(raw_default),
                "matched_rule": "default",
            }

        return {
            "decision": default_decision,
            "reasons": [],
            "obligations": [],
            "matched_rule": "default",
        }

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> PolicyDefinitionDE:
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
            abort(404, "Policy definition not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_with_row_version(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> PolicyDefinitionDE:
        svc: ICrudServiceWithRowVersion[PolicyDefinitionDE] = self

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

    async def action_evaluate_policy(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: EvaluatePolicyActionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Evaluate a policy and append a policy decision log record."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if not bool(current.is_active):
            abort(409, "Policy definition is inactive.")

        trace_id = self._normalize_optional_text(data.trace_id)
        policy_code = self._normalize_optional_text(current.code)
        policy_version = (
            int(current.version or 0) if current.version is not None else None
        )
        now = self._now_utc()

        reasons: list[str] = []
        obligations: list[Any] = []
        matched_rule: str | None = None
        allow: bool

        decision: str
        outcome: str
        input_json: dict[str, Any] | None = (
            dict(data.input_json) if data.input_json is not None else None
        )
        actor_json: dict[str, Any] | None = (
            dict(data.actor_json) if data.actor_json is not None else None
        )

        if data.decision is not None:
            decision = self._normalize_decision(data.decision)
            outcome = self._normalize_outcome(data.outcome or "applied")
            reason = self._normalize_optional_text(data.reason)
            if reason is not None:
                reasons.append(reason)
            allow = decision != "deny"
            decision_json = {
                "Mode": "legacy",
                "Decision": decision,
                "Outcome": outcome,
                "Allow": allow,
                "Reasons": reasons,
                "Obligations": obligations,
            }
        else:
            if data.input_json is None:
                abort(400, "InputJson must be provided in PDP mode.")
            document = self._as_mapping(
                current.document_json,
                field_name="DocumentJson",
            )

            try:
                evaluation = self._evaluate_document(
                    document=document,
                    input_json=dict(data.input_json),
                )
            except ValueError as error:
                abort(409, str(error))

            decision = str(evaluation["decision"])
            outcome = self._OUTCOME_BY_DECISION[decision]
            reasons = list(evaluation.get("reasons", []))
            obligations = list(evaluation.get("obligations", []))
            matched_rule = self._normalize_optional_text(
                evaluation.get("matched_rule")
                if isinstance(evaluation.get("matched_rule"), str)
                else None
            )
            allow = decision != "deny"
            decision_json = {
                "Mode": "pdp",
                "Decision": decision,
                "Outcome": outcome,
                "Allow": allow,
                "Reasons": reasons,
                "Obligations": obligations,
                "MatchedRule": matched_rule,
            }

        reason = reasons[0] if reasons else self._normalize_optional_text(data.reason)
        decision_log = await self._decision_log_service.create(
            {
                "tenant_id": tenant_id,
                "policy_definition_id": entity_id,
                "trace_id": trace_id,
                "policy_key": policy_code,
                "policy_version": policy_version,
                "subject_namespace": data.subject_namespace,
                "subject_id": data.subject_id,
                "subject_ref": self._normalize_optional_text(data.subject_ref),
                "decision": decision,
                "outcome": outcome,
                "reason": reason,
                "evaluated_at": now,
                "evaluator_user_id": auth_user_id,
                "request_context": data.request_context,
                "actor_json": actor_json,
                "input_json": input_json,
                "decision_json": decision_json,
                "attributes": data.attributes,
            }
        )

        await self._update_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "last_evaluated_at": now,
                "last_evaluated_by_user_id": auth_user_id,
                "last_decision_log_id": decision_log.id,
            },
        )

        return (
            {
                "DecisionLogId": str(decision_log.id),
                "Decision": decision,
                "Outcome": outcome,
                "Allow": allow,
                "Reasons": reasons,
                "Obligations": obligations,
                "PolicyCode": policy_code,
                "PolicyVersion": policy_version,
                "TraceId": trace_id,
            },
            200,
        )

    async def action_activate_version(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: ActivatePolicyVersionActionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Activate one version and deactivate sibling versions with same code."""
        expected_row_version = int(data.row_version)
        anchor = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        code = self._normalize_optional_text(anchor.code)
        if code is None:
            abort(409, "Policy definition code is required.")

        target_version = int(data.version)
        candidates = await self.list(
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "code": code,
                        "version": target_version,
                    }
                )
            ],
            limit=2,
        )
        if not candidates:
            abort(404, "Target policy version not found.")
        if len(candidates) > 1:
            abort(409, "Multiple policy rows found for the target version.")
        target = candidates[0]
        if target.id is None:
            abort(409, "Target policy ID is missing.")

        siblings = await self.list(
            filter_groups=[FilterGroup(where={"tenant_id": tenant_id, "code": code})]
        )

        for sibling in siblings:
            if sibling.id is None:
                continue
            if sibling.id == target.id:
                continue
            if not bool(sibling.is_active):
                continue
            expected = int(sibling.row_version or 0)
            if expected <= 0:
                abort(409, "Sibling policy RowVersion is invalid.")
            await self._update_with_row_version(
                where={"tenant_id": tenant_id, "id": sibling.id},
                expected_row_version=expected,
                changes={"is_active": False},
            )

        if not bool(target.is_active):
            target_expected = int(target.row_version or 0)
            if target_expected <= 0:
                abort(409, "Target policy RowVersion is invalid.")
            target = await self._update_with_row_version(
                where={"tenant_id": tenant_id, "id": target.id},
                expected_row_version=target_expected,
                changes={"is_active": True},
            )

        return (
            {
                "PolicyId": str(target.id),
                "Code": code,
                "Version": int(target.version or target_version),
                "IsActive": bool(target.is_active),
                "ActivatedByActionOnPolicyId": str(entity_id),
            },
            200,
        )

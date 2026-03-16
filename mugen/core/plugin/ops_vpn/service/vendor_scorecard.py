"""Provides a CRUD service for vendor scorecards and score rollups."""

__all__ = ["VendorScorecardService"]

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from quart import abort

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    ScalarFilter,
    ScalarFilterOp,
)
from mugen.core.plugin.ops_vpn.api.validation import VendorScorecardRollupValidation
from mugen.core.plugin.ops_vpn.contract.service.vendor_scorecard import (
    IVendorScorecardService,
)
from mugen.core.plugin.ops_vpn.domain import VendorScorecardDE


class VendorScorecardService(
    IRelationalService[VendorScorecardDE],
    IVendorScorecardService,
):
    """A CRUD service for vendor scorecards."""

    _EVENT_TABLE = "ops_vpn_vendor_performance_event"
    _VENDOR_TABLE = "ops_vpn_vendor"
    _POLICY_TABLE = "ops_vpn_scorecard_policy"
    _DEFAULT_POLICY_CODE = "default"

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=VendorScorecardDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    @staticmethod
    def _safe_score(raw: float | int | None) -> int | None:
        if raw is None:
            return None
        bounded = max(0, min(100, float(raw)))
        return int(round(bounded))

    @staticmethod
    def _tokenize_enum_value(raw: Any) -> str:
        """Normalize enum-backed DB values to their lower-case token."""
        if raw is None:
            return ""

        if isinstance(raw, Enum):
            raw = raw.value

        return str(raw).strip().lower()

    @classmethod
    def _normalized_event_score(
        cls, metric_type: str, row: Mapping[str, Any]
    ) -> int | None:
        normalized = row.get("normalized_score")
        if normalized is not None:
            return cls._safe_score(normalized)

        numerator = row.get("metric_numerator")
        denominator = row.get("metric_denominator")

        if numerator is None or denominator in (None, 0):
            return None

        ratio = float(numerator) / float(denominator)
        ratio = max(0.0, min(1.0, ratio))

        if metric_type == "complaint_rate":
            return cls._safe_score((1.0 - ratio) * 100.0)

        if metric_type in {
            "completion_rate",
            "response_sla_adherence",
        }:
            return cls._safe_score(ratio * 100.0)

        return None

    @classmethod
    def _avg_score(cls, values: list[int]) -> int | None:
        if not values:
            return None
        return cls._safe_score(sum(values) / len(values))

    @classmethod
    def _coerce_policy_int(cls, raw: Any, *, default: int, minimum: int = 0) -> int:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default
        return max(minimum, value)

    async def _resolve_policy(self, tenant_id: uuid.UUID) -> dict[str, Any]:
        policy = await self._rsg.get_one(
            self._POLICY_TABLE,
            where={
                "tenant_id": tenant_id,
                "code": self._DEFAULT_POLICY_CODE,
            },
            columns=[
                "time_to_quote_weight",
                "completion_rate_weight",
                "complaint_rate_weight",
                "response_sla_weight",
                "min_sample_size",
                "minimum_overall_score",
                "require_all_metrics",
            ],
        )

        defaults = {
            "time_to_quote_weight": 25,
            "completion_rate_weight": 25,
            "complaint_rate_weight": 25,
            "response_sla_weight": 25,
            "min_sample_size": 1,
            "minimum_overall_score": 0,
            "require_all_metrics": False,
        }
        if policy is None:
            return defaults

        resolved = dict(defaults)
        resolved.update(policy)
        return resolved

    async def rollup_period(
        self,
        *,
        tenant_id: uuid.UUID,
        vendor_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
    ) -> VendorScorecardDE:
        """Roll up events for a vendor and persist a period snapshot."""
        if period_end < period_start:
            abort(400, "PeriodEnd must be greater than or equal to PeriodStart.")

        events = await self._rsg.find_many(
            self._EVENT_TABLE,
            filter_groups=[
                FilterGroup(
                    where={"tenant_id": tenant_id, "vendor_id": vendor_id},
                    scalar_filters=[
                        ScalarFilter(
                            field="observed_at",
                            op=ScalarFilterOp.GTE,
                            value=period_start,
                        ),
                        ScalarFilter(
                            field="observed_at",
                            op=ScalarFilterOp.LTE,
                            value=period_end,
                        ),
                    ],
                )
            ],
        )

        buckets: dict[str, list[int]] = {
            "time_to_quote": [],
            "completion_rate": [],
            "complaint_rate": [],
            "response_sla_adherence": [],
        }

        for row in events:
            metric_type = self._tokenize_enum_value(row.get("metric_type"))
            if metric_type not in buckets:
                continue
            score = self._normalized_event_score(metric_type, row)
            if score is not None:
                buckets[metric_type].append(score)

        time_to_quote_score = self._avg_score(buckets["time_to_quote"])
        completion_rate_score = self._avg_score(buckets["completion_rate"])
        complaint_rate_score = self._avg_score(buckets["complaint_rate"])
        response_sla_score = self._avg_score(buckets["response_sla_adherence"])

        metric_scores = {
            "time_to_quote": time_to_quote_score,
            "completion_rate": completion_rate_score,
            "complaint_rate": complaint_rate_score,
            "response_sla_adherence": response_sla_score,
        }

        vendor_row = await self._rsg.get_one(
            self._VENDOR_TABLE,
            where={"tenant_id": tenant_id, "id": vendor_id},
            columns=["status", "next_reverification_due_at"],
        )
        if vendor_row is None:
            abort(404, "Vendor not found.")

        policy = await self._resolve_policy(tenant_id)
        weights = {
            "time_to_quote": self._coerce_policy_int(
                policy.get("time_to_quote_weight"),
                default=25,
            ),
            "completion_rate": self._coerce_policy_int(
                policy.get("completion_rate_weight"),
                default=25,
            ),
            "complaint_rate": self._coerce_policy_int(
                policy.get("complaint_rate_weight"),
                default=25,
            ),
            "response_sla_adherence": self._coerce_policy_int(
                policy.get("response_sla_weight"),
                default=25,
            ),
        }

        weighted_pairs: list[tuple[int, int]] = []
        for metric_name, score in metric_scores.items():
            if score is None:
                continue
            weight = weights.get(metric_name, 0)
            if weight > 0:
                weighted_pairs.append((score, weight))

        if weighted_pairs:
            weighted_total = sum(score * weight for score, weight in weighted_pairs)
            weight_total = sum(weight for _, weight in weighted_pairs)
            overall_score = self._safe_score(weighted_total / weight_total)
        else:
            overall_score = None

        now = datetime.now(timezone.utc)
        reverification_due = bool(
            vendor_row.get("next_reverification_due_at") is not None
            and vendor_row["next_reverification_due_at"] <= now
        )
        vendor_status = self._tokenize_enum_value(vendor_row.get("status"))

        min_sample_size = self._coerce_policy_int(
            policy.get("min_sample_size"),
            default=1,
            minimum=1,
        )
        minimum_overall_score = max(
            0,
            min(
                100,
                self._coerce_policy_int(
                    policy.get("minimum_overall_score"),
                    default=0,
                ),
            ),
        )
        require_all_metrics = bool(policy.get("require_all_metrics", False))

        sample_size_total = 0
        for row in events:
            sample_size_total += self._coerce_policy_int(
                row.get("sample_size"),
                default=1,
                minimum=1,
            )

        missing_metric_keys = [k for k, v in metric_scores.items() if v is None]
        is_routable = (
            vendor_status == "active"
            and not reverification_due
            and overall_score is not None
            and overall_score >= minimum_overall_score
            and sample_size_total >= min_sample_size
            and (not require_all_metrics or not missing_metric_keys)
        )

        missing_metrics = [k for k, values in buckets.items() if not values]
        status_flags = {
            "vendor_status": vendor_status,
            "reverification_due": reverification_due,
            "missing_metrics": missing_metrics,
            "has_score": overall_score is not None,
            "policy": {
                "code": self._DEFAULT_POLICY_CODE,
                "weights": weights,
                "min_sample_size": min_sample_size,
                "minimum_overall_score": minimum_overall_score,
                "require_all_metrics": require_all_metrics,
            },
            "sample_size_total": sample_size_total,
        }

        where = {
            "tenant_id": tenant_id,
            "vendor_id": vendor_id,
            "period_start": period_start,
            "period_end": period_end,
        }

        changes = {
            "time_to_quote_score": time_to_quote_score,
            "completion_rate_score": completion_rate_score,
            "complaint_rate_score": complaint_rate_score,
            "response_sla_score": response_sla_score,
            "overall_score": overall_score,
            "event_count": len(events),
            "is_routable": is_routable,
            "status_flags": status_flags,
            "computed_at": now,
        }

        existing = await self.get(where)
        if existing is None:
            return await self.create(
                {
                    **where,
                    **changes,
                }
            )

        updated = await self.update(where, changes)
        if updated is None:
            abort(404, "Scorecard update not performed. No row matched.")
        return updated

    async def action_rollup(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],  # noqa: ARG002
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: VendorScorecardRollupValidation,
    ) -> dict[str, Any]:
        """Run rollup for the requested vendor and period."""
        scorecard = await self.rollup_period(
            tenant_id=tenant_id,
            vendor_id=data.vendor_id,
            period_start=data.period_start,
            period_end=data.period_end,
        )

        return {
            "Id": str(scorecard.id),
            "VendorId": str(scorecard.vendor_id),
            "PeriodStart": (
                scorecard.period_start.isoformat() if scorecard.period_start else None
            ),
            "PeriodEnd": (
                scorecard.period_end.isoformat() if scorecard.period_end else None
            ),
            "OverallScore": scorecard.overall_score,
            "IsRoutable": scorecard.is_routable,
        }

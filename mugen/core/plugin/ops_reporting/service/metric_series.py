"""Provides a CRUD service for metric series rows."""

__all__ = ["MetricSeriesService"]

from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy.exc import IntegrityError

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_reporting.contract.service.metric_series import (
    IMetricSeriesService,
)
from mugen.core.plugin.ops_reporting.domain import MetricSeriesDE


class MetricSeriesService(  # pylint: disable=too-few-public-methods
    IRelationalService[MetricSeriesDE],
    IMetricSeriesService,
):
    """A CRUD service for idempotent metric series upserts."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=MetricSeriesDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_scope_key(value: str | None) -> str:
        clean = str(value or "").strip()
        return clean or "__all__"

    async def create(self, values: Mapping[str, Any]) -> MetricSeriesDE:
        """Create metric-series rows idempotently by tenant+aggregation_key."""
        create_values = dict(values)
        create_values["scope_key"] = self._normalize_scope_key(
            create_values.get("scope_key")
        )

        create_values["source_count"] = int(create_values.get("source_count") or 0)
        create_values["value_numeric"] = int(create_values.get("value_numeric") or 0)
        create_values.setdefault("computed_at", self._now_utc())

        aggregation_key = str(create_values.get("aggregation_key") or "").strip()
        create_values["aggregation_key"] = aggregation_key

        tenant_id = create_values.get("tenant_id")
        if tenant_id is not None and aggregation_key:
            existing = await self.get(
                where={
                    "tenant_id": tenant_id,
                    "aggregation_key": aggregation_key,
                }
            )
            if existing is not None:
                return existing

        try:
            return await super().create(create_values)
        except IntegrityError:
            if tenant_id is not None and aggregation_key:
                existing = await self.get(
                    where={
                        "tenant_id": tenant_id,
                        "aggregation_key": aggregation_key,
                    }
                )
                if existing is not None:
                    return existing
            raise

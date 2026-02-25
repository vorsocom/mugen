"""Provides a service for the SchemaBinding declarative model."""

__all__ = ["SchemaBindingService"]

import uuid
from typing import Any, Sequence

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup, OrderBy
from mugen.core.plugin.acp.contract.service.schema_binding import ISchemaBindingService
from mugen.core.plugin.acp.domain import SchemaBindingDE


class SchemaBindingService(
    IRelationalService[SchemaBindingDE],
    ISchemaBindingService,
):
    """A service for ACP schema bindings."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=SchemaBindingDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def list_active_bindings(
        self,
        *,
        tenant_id: uuid.UUID,
        target_namespace: str,
        target_entity_set: str,
        target_action: str | None,
        binding_kind: str,
    ) -> Sequence[SchemaBindingDE]:
        """List active schema bindings that apply to a target operation."""
        base_where = {
            "tenant_id": tenant_id,
            "target_namespace": target_namespace,
            "target_entity_set": target_entity_set,
            "binding_kind": binding_kind,
            "is_active": True,
        }

        groups: list[FilterGroup] = []
        if target_action is None:
            groups.append(
                FilterGroup(
                    where={
                        **base_where,
                        "target_action": None,
                    }
                )
            )
        else:
            groups.append(
                FilterGroup(
                    where={
                        **base_where,
                        "target_action": target_action,
                    }
                )
            )
            groups.append(
                FilterGroup(
                    where={
                        **base_where,
                        "target_action": None,
                    }
                )
            )

        rows = await self.list(
            filter_groups=groups,
            order_by=[
                OrderBy("target_action", descending=False),
                OrderBy("id", descending=False),
            ],
        )

        unique_rows: dict[uuid.UUID, SchemaBindingDE] = {}
        for row in rows:
            if row.id is None:
                continue
            unique_rows[row.id] = row

        return list(unique_rows.values())

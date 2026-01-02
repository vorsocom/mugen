"""
Docstring for mugen.core.plugin.acp.utility.rgql.default_where
"""

from typing import Any, Callable
import uuid

from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.sdk.resource import SoftDeleteMode
from mugen.core.utility.string.case_conversion_helper import title_to_snake


def make_default_where_provider(
    *,
    registry: IAdminRegistry,
    tenant_id: uuid.UUID | None = None,
    include_deleted: bool = False,
) -> Callable[[str], dict[str, Any]]:
    """
    Returns a closure: type_name -> enforced where constraints.

    - Tenant scoping: if the EdmType defines 'TenantId' AND tenant_id is not None,
      enforce tenant_id filter.
    - Soft delete: if include_deleted is False and resource has soft delete enabled,
      enforce not-deleted predicate.
    """

    # Precompute lookup maps for speed in deep expansions.
    type_index = {t.name: t for t in registry.schema.types.values()}
    resource_by_type = {res.edm_type_name: res for res in registry.resources.values()}

    def default_where_provider(type_name: str) -> dict[str, Any]:
        out: dict[str, Any] = {}

        edm_type = type_index.get(type_name)
        if edm_type is None:
            return out

        # Tenant scope based on convention: TenantId property exists.
        if tenant_id is not None and "TenantId" in edm_type.properties:
            # Your relational layer uses snake_case column names in FilterGroup.where;
            # adapt if you store as TitleCase in the EDM.
            out["tenant_id"] = tenant_id

        # Soft delete (admin-controlled; example assumes per-resource behavior)
        if not include_deleted:
            res = resource_by_type.get(type_name)
            if res is not None:
                # Example: behavior.soft_delete_policy with mode/column
                policy = res.behavior.soft_delete
                if policy and policy.mode != SoftDeleteMode.NONE and policy.column:
                    if policy.mode == SoftDeleteMode.TIMESTAMP:
                        out[title_to_snake(policy.column)] = None
                    elif policy.mode == SoftDeleteMode.FLAG:
                        out[title_to_snake(policy.column)] = False

        return out

    return default_where_provider

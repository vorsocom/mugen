"""Knowledge Pack plugin contribution entrypoint.

Contributes generic knowledge-pack resources into ACP.
"""

import re
from typing import Any

from mugen.core.plugin.acp.contract.sdk.binding import (
    EdmTypeSpec,
    RelationalServiceSpec,
    TableSpec,
)
from mugen.core.plugin.acp.contract.sdk.permission import (
    DefaultGlobalGrant,
    PermissionObjectDef,
)
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.sdk.resource import (
    AdminBehavior,
    AdminCapabilities,
    AdminPermissions,
    AdminResource,
    CrudPolicy,
    SoftDeletePolicy,
)
from mugen.core.plugin.acp.contract.sdk.seed import SystemFlagDef
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.knowledge_pack.api.validation import (
    KnowledgeEntryCreateValidation,
    KnowledgeEntryRevisionUpdateValidation,
    KnowledgeEntryUpdateValidation,
    KnowledgeEntryRevisionCreateValidation,
    KnowledgePackCreateValidation,
    KnowledgePackUpdateValidation,
    KnowledgePackVersionCreateValidation,
    KnowledgePackVersionUpdateValidation,
    KnowledgePackApproveValidation,
    KnowledgePackArchiveValidation,
    KnowledgePackPublishValidation,
    KnowledgePackRejectValidation,
    KnowledgePackRollbackVersionValidation,
    KnowledgePackSubmitForReviewValidation,
    KnowledgeScopeCreateValidation,
    KnowledgeScopeUpdateValidation,
)
from mugen.core.utility.string.case_conversion_helper import title_to_snake

_WORD_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+|\d+")


def _humanize(s: str) -> str:
    """Convert PascalCase/camelCase identifiers into a display title."""
    return " ".join(_WORD_RE.findall(s)).strip()


# pylint: disable=too-many-locals
def contribute(
    registry: IAdminRegistry,
    *,
    admin_namespace: str,
    plugin_namespace: str,
) -> None:
    """Contribute knowledge_pack resources into the ACP registry."""
    admin_ns = AdminNs(admin_namespace)
    plugin_ns = AdminNs(plugin_namespace)

    registry.register_system_flag(
        SystemFlagDef(
            namespace=plugin_ns.ns,
            name="installed",
            description="Knowledge Pack plugin installed.",
            is_set=True,
        )
    )

    resources: tuple[dict[str, Any], ...] = (
        {
            "set": "KnowledgePacks",
            "entity": "KnowledgePack",
            "description": (
                "Tenant-scoped generic knowledge-pack containers for approved"
                " response governance."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=KnowledgePackCreateValidation,
                update_schema=KnowledgePackUpdateValidation,
            ),
        },
        {
            "set": "KnowledgePackVersions",
            "entity": "KnowledgePackVersion",
            "description": (
                "Versioned lifecycle records (draft/review/approved/published/"
                "archived) for knowledge packs."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": True,
            "crud": CrudPolicy(
                create_schema=KnowledgePackVersionCreateValidation,
                update_schema=KnowledgePackVersionUpdateValidation,
            ),
            "actions": {
                "submit_for_review": {
                    "perm": admin_ns.verb("manage"),
                    "schema": KnowledgePackSubmitForReviewValidation,
                    "confirm": "Submit this version for review?",
                },
                "approve": {
                    "perm": admin_ns.verb("manage"),
                    "schema": KnowledgePackApproveValidation,
                    "confirm": "Approve this version?",
                },
                "reject": {
                    "perm": admin_ns.verb("manage"),
                    "schema": KnowledgePackRejectValidation,
                    "confirm": "Reject this version back to draft?",
                },
                "publish": {
                    "perm": admin_ns.verb("manage"),
                    "schema": KnowledgePackPublishValidation,
                    "confirm": "Publish this version?",
                },
                "archive": {
                    "perm": admin_ns.verb("manage"),
                    "schema": KnowledgePackArchiveValidation,
                    "confirm": "Archive this version?",
                },
                "rollback_version": {
                    "perm": admin_ns.verb("manage"),
                    "schema": KnowledgePackRollbackVersionValidation,
                    "confirm": "Rollback publication to this version?",
                },
            },
        },
        {
            "set": "KnowledgeEntries",
            "entity": "KnowledgeEntry",
            "description": (
                "Knowledge items owned by a specific pack version."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=KnowledgeEntryCreateValidation,
                update_schema=KnowledgeEntryUpdateValidation,
            ),
        },
        {
            "set": "KnowledgeEntryRevisions",
            "entity": "KnowledgeEntryRevision",
            "description": (
                "Revision records that hold publish-state-controlled entry content."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=KnowledgeEntryRevisionCreateValidation,
                update_schema=KnowledgeEntryRevisionUpdateValidation,
            ),
        },
        {
            "set": "KnowledgeApprovals",
            "entity": "KnowledgeApproval",
            "description": (
                "Append-only governance approvals and publish decisions."
            ),
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "crud": CrudPolicy(),
        },
        {
            "set": "KnowledgeScopes",
            "entity": "KnowledgeScope",
            "description": (
                "Scoped retrieval constraints (tenant/channel/locale/category)"
                " bound to specific revisions."
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "crud": CrudPolicy(
                create_schema=KnowledgeScopeCreateValidation,
                update_schema=KnowledgeScopeUpdateValidation,
            ),
        },
    )

    kp_objects: list[PermissionObjectDef] = []
    for resource in resources:
        obj_name = title_to_snake(resource["entity"])
        obj = PermissionObjectDef(plugin_ns.ns, obj_name)
        kp_objects.append(obj)
        registry.register_permission_object(obj)

    kp_obj_keys = [obj.key for obj in kp_objects]
    admin_verb_keys = [
        admin_ns.verb(verb) for verb in ("read", "create", "update", "delete", "manage")
    ]

    registry.register_default_global_grants(
        DefaultGlobalGrant(admin_ns.key("administrator"), pobj, ptyp, True)
        for pobj in kp_obj_keys
        for ptyp in admin_verb_keys
    )

    for resource in resources:
        entity_set = resource["set"]
        entity = resource["entity"]

        obj_name = title_to_snake(entity)
        pobj = PermissionObjectDef(plugin_ns.ns, obj_name)

        edm_type_name = f"KNOWLEDGEPACK.{entity}"
        service_key = f"{admin_ns.ns}:{edm_type_name}"
        table_name = str(resource.get("table_name", f"knowledge_pack_{obj_name}"))

        registry.register_resource(
            AdminResource(
                namespace=plugin_ns.ns,
                entity_set=entity_set,
                edm_type_name=edm_type_name,
                perm_obj=pobj.key,
                service_key=service_key,
                permissions=AdminPermissions(
                    permission_object=pobj.key,
                    read=admin_ns.verb("read"),
                    create=admin_ns.verb("create"),
                    update=admin_ns.verb("update"),
                    delete=admin_ns.verb("delete"),
                    manage=admin_ns.verb("manage"),
                ),
                capabilities=AdminCapabilities(
                    allow_read=bool(resource.get("allow_read", True)),
                    allow_create=bool(resource.get("allow_create", False)),
                    allow_update=bool(resource.get("allow_update", False)),
                    allow_delete=bool(resource.get("allow_delete", False)),
                    allow_manage=bool(resource.get("allow_manage", False)),
                    actions=dict(resource.get("actions", {})),
                ),
                behavior=AdminBehavior(
                    soft_delete=resource.get("soft_delete", SoftDeletePolicy()),
                    rgql_enabled=True,
                ),
                crud=resource.get("crud", CrudPolicy()),
                title=_humanize(entity_set),
                description=resource["description"],
            )
        )

        registry.register_table_spec(
            TableSpec(
                table_name=table_name,
                table_provider=(
                    f"mugen.core.plugin.knowledge_pack.model.{obj_name}:{entity}"
                ),
            )
        )

        registry.register_edm_type_spec(
            EdmTypeSpec(
                edm_type_name=edm_type_name,
                edm_provider=(
                    f"mugen.core.plugin.knowledge_pack.edm:{obj_name}_type"
                ),
            )
        )

        registry.register_service_spec(
            RelationalServiceSpec(
                service_key=service_key,
                service_cls=(
                    "mugen.core.plugin.knowledge_pack.service."
                    f"{obj_name}:{entity}Service"
                ),
                init_kwargs={"table": table_name},
            )
        )

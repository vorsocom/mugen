"""Audit plugin contribution entrypoint."""

import re

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
)
from mugen.core.plugin.acp.contract.sdk.seed import SystemFlagDef
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.audit.api.validation import (
    AuditEventPlaceLegalHoldValidation,
    AuditEventRedactValidation,
    AuditEventReleaseLegalHoldValidation,
    AuditEventRunLifecycleValidation,
    AuditEventSealBacklogValidation,
    AuditEventTombstoneValidation,
    AuditEventVerifyChainValidation,
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
    """Contribute audit artifacts into the ACP registry."""
    admin_ns = AdminNs(admin_namespace)
    plugin_ns = AdminNs(plugin_namespace)

    registry.register_system_flag(
        SystemFlagDef(
            namespace=plugin_ns.ns,
            name="installed",
            description="Audit plugin installed.",
            is_set=True,
        )
    )

    entity_set = "AuditEvents"
    entity = "AuditEvent"
    entity_name = title_to_snake(entity)

    pobj = PermissionObjectDef(plugin_ns.ns, entity_name)
    registry.register_permission_object(pobj)

    admin_verb_keys = [
        admin_ns.verb(v) for v in ("read", "create", "update", "delete", "manage")
    ]

    registry.register_default_global_grants(
        [
            DefaultGlobalGrant(admin_ns.key("administrator"), pobj.key, ptyp, True)
            for ptyp in admin_verb_keys
        ]
    )

    edm_type_name = f"AUDIT.{entity}"
    service_key = f"{admin_ns.ns}:{edm_type_name}"

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
                allow_read=True,
                allow_create=False,
                allow_update=False,
                allow_delete=False,
                allow_manage=True,
                actions={
                    "place_legal_hold": {
                        "perm": admin_ns.verb("manage"),
                        "schema": AuditEventPlaceLegalHoldValidation,
                        "confirm": "Place legal hold on this audit event?",
                    },
                    "release_legal_hold": {
                        "perm": admin_ns.verb("manage"),
                        "schema": AuditEventReleaseLegalHoldValidation,
                        "confirm": "Release legal hold on this audit event?",
                    },
                    "redact": {
                        "perm": admin_ns.verb("manage"),
                        "schema": AuditEventRedactValidation,
                        "confirm": "Redact this audit event snapshot data?",
                    },
                    "tombstone": {
                        "perm": admin_ns.verb("manage"),
                        "schema": AuditEventTombstoneValidation,
                        "confirm": "Tombstone this audit event for purge scheduling?",
                    },
                    "run_lifecycle": {
                        "perm": admin_ns.verb("manage"),
                        "schema": AuditEventRunLifecycleValidation,
                        "confirm": "Run audit lifecycle phases now?",
                    },
                    "verify_chain": {
                        "perm": admin_ns.verb("manage"),
                        "schema": AuditEventVerifyChainValidation,
                        "confirm": "Verify audit hash chain integrity?",
                    },
                    "seal_backlog": {
                        "perm": admin_ns.verb("manage"),
                        "schema": AuditEventSealBacklogValidation,
                        "confirm": "Seal unchained audit backlog rows now?",
                    },
                },
            ),
            behavior=AdminBehavior(rgql_enabled=True),
            crud=CrudPolicy(),
            title=_humanize(entity_set),
            description=(
                "Append-only audit records for ACP CRUD writes and action execution."
            ),
        )
    )

    registry.register_table_spec(
        TableSpec(
            table_name="audit_event",
            table_provider="mugen.core.plugin.audit.model.audit_event:AuditEvent",
        )
    )
    registry.register_table_spec(
        TableSpec(
            table_name="audit_chain_head",
            table_provider=(
                "mugen.core.plugin.audit.model.audit_chain_head:AuditChainHead"
            ),
        )
    )

    registry.register_edm_type_spec(
        EdmTypeSpec(
            edm_type_name=edm_type_name,
            edm_provider="mugen.core.plugin.audit.edm:audit_event_type",
        )
    )

    registry.register_service_spec(
        RelationalServiceSpec(
            service_key=service_key,
            service_cls="mugen.core.plugin.audit.service.audit_event:AuditEventService",
            init_kwargs={"table": "audit_event"},
        )
    )

"""Public API for the admin.service package."""

__all__ = [
    "DedupRecordService",
    "GlobalPermissionEntryService",
    "GlobalRoleMembershipService",
    "GlobalRoleService",
    "KeyRefService",
    "MessagingClientProfileService",
    "PermissionEntryService",
    "PermissionObjectService",
    "PermissionTypeService",
    "PluginCapabilityGrantService",
    "PersonService",
    "RefreshTokenService",
    "RoleService",
    "RoleMembershipService",
    "RuntimeConfigProfileService",
    "SchemaBindingService",
    "SchemaDefinitionService",
    "SystemFlagService",
    "TenantService",
    "TenantDomainService",
    "TenantInvitationService",
    "TenantMembershipService",
    "UserService",
    "REGISTRATIONS",
]

from mugen.core.plugin.acp import model as admin_model
from mugen.core.plugin.acp.service.dedup_record import DedupRecordService
from mugen.core.plugin.acp.service.global_permission_entry import (
    GlobalPermissionEntryService,
)
from mugen.core.plugin.acp.service.global_role import GlobalRoleService
from mugen.core.plugin.acp.service.global_role_membership import (
    GlobalRoleMembershipService,
)
from mugen.core.plugin.acp.service.key_ref import KeyRefService
from mugen.core.plugin.acp.service.messaging_client_profile import (
    MessagingClientProfileService,
)
from mugen.core.plugin.acp.service.permission_entry import PermissionEntryService
from mugen.core.plugin.acp.service.permission_object import PermissionObjectService
from mugen.core.plugin.acp.service.permission_type import PermissionTypeService
from mugen.core.plugin.acp.service.plugin_capability_grant import (
    PluginCapabilityGrantService,
)
from mugen.core.plugin.acp.service.person import PersonService
from mugen.core.plugin.acp.service.refresh_token import RefreshTokenService
from mugen.core.plugin.acp.service.role import RoleService
from mugen.core.plugin.acp.service.role_membership import RoleMembershipService
from mugen.core.plugin.acp.service.runtime_config_profile import (
    RuntimeConfigProfileService,
)
from mugen.core.plugin.acp.service.schema_binding import SchemaBindingService
from mugen.core.plugin.acp.service.schema_definition import SchemaDefinitionService
from mugen.core.plugin.acp.service.system_flag import SystemFlagService
from mugen.core.plugin.acp.service.tenant import TenantService
from mugen.core.plugin.acp.service.tenant_domain import TenantDomainService
from mugen.core.plugin.acp.service.tenant_invitation import TenantInvitationService
from mugen.core.plugin.acp.service.tenant_membership import TenantMembershipService
from mugen.core.plugin.acp.service.user import UserService

REGISTRATIONS = [
    (DedupRecordService, admin_model.DedupRecord),
    (GlobalPermissionEntryService, admin_model.GlobalPermissionEntry),
    (GlobalRoleService, admin_model.GlobalRole),
    (GlobalRoleMembershipService, admin_model.GlobalRoleMembership),
    (KeyRefService, admin_model.KeyRef),
    (MessagingClientProfileService, admin_model.MessagingClientProfile),
    (PermissionEntryService, admin_model.PermissionEntry),
    (PermissionObjectService, admin_model.PermissionObject),
    (PermissionTypeService, admin_model.PermissionType),
    (PluginCapabilityGrantService, admin_model.PluginCapabilityGrant),
    (PersonService, admin_model.Person),
    (RefreshTokenService, admin_model.RefreshToken),
    (RoleService, admin_model.Role),
    (RoleMembershipService, admin_model.RoleMembership),
    (RuntimeConfigProfileService, admin_model.RuntimeConfigProfile),
    (SchemaBindingService, admin_model.SchemaBinding),
    (SchemaDefinitionService, admin_model.SchemaDefinition),
    (SystemFlagService, admin_model.SystemFlag),
    (TenantService, admin_model.Tenant),
    (TenantDomainService, admin_model.TenantDomain),
    (TenantInvitationService, admin_model.TenantInvitation),
    (TenantMembershipService, admin_model.TenantMembership),
    (UserService, admin_model.User),
]

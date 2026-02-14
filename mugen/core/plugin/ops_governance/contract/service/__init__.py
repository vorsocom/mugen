"""Public API for ops_governance service contracts."""

__all__ = [
    "IConsentRecordService",
    "IDelegationGrantService",
    "IPolicyDefinitionService",
    "IPolicyDecisionLogService",
    "IRetentionPolicyService",
    "IDataHandlingRecordService",
]

from mugen.core.plugin.ops_governance.contract.service.consent_record import (
    IConsentRecordService,
)
from mugen.core.plugin.ops_governance.contract.service.delegation_grant import (
    IDelegationGrantService,
)
from mugen.core.plugin.ops_governance.contract.service.policy_definition import (
    IPolicyDefinitionService,
)
from mugen.core.plugin.ops_governance.contract.service.policy_decision_log import (
    IPolicyDecisionLogService,
)
from mugen.core.plugin.ops_governance.contract.service.retention_policy import (
    IRetentionPolicyService,
)
from mugen.core.plugin.ops_governance.contract.service.data_handling_record import (
    IDataHandlingRecordService,
)

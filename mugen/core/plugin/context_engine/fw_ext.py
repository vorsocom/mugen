"""Framework extension for context_engine runtime registration."""

from __future__ import annotations

__all__ = ["ContextEngineFWExtension"]

from types import SimpleNamespace

from quart import Quart

from mugen.core import di
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.contract.gateway.storage.rdbms import IRelationalStorageGateway
from mugen.core.gateway.storage.rdbms.sqla.sqla_gateway import (
    SQLAlchemyRelationalStorageGateway,
)
from mugen.core.plugin.audit.service.audit_biz_trace_event import (
    AuditBizTraceEventService,
)
from mugen.core.plugin.channel_orchestration.service.conversation_state import (
    ConversationStateService,
)
from mugen.core.plugin.channel_orchestration.service.work_item import WorkItemService
from mugen.core.plugin.context_engine.service import (
    AuditContributor,
    ChannelOrchestrationContributor,
    ContextCacheRecordService,
    ContextComponentRegistry,
    ContextContributorBindingService,
    ContextEventLogService,
    ContextMemoryRecordService,
    ContextPolicyService,
    ContextProfileService,
    ContextSourceBindingService,
    ContextStateSnapshotService,
    ContextTracePolicyService,
    ContextTraceService,
    DefaultContextGuard,
    DefaultContextPolicyResolver,
    DefaultContextRanker,
    DefaultMemoryWriter,
    KnowledgePackContributor,
    MemoryContributor,
    OpsCaseContributor,
    PersonaPolicyContributor,
    RecentTurnContributor,
    RelationalContextCache,
    RelationalContextStateStore,
    RelationalContextTraceSink,
    StateContributor,
)
from mugen.core.plugin.context_engine.model import (
    ContextCacheRecord,
    ContextEventLog,
    ContextMemoryRecord,
    ContextStateSnapshot,
    ContextTrace,
)
from mugen.core.plugin.knowledge_pack.service.knowledge_scope import KnowledgeScopeService
from mugen.core.plugin.ops_case.service.case import CaseService
from mugen.core.plugin.ops_case.service.case_event import CaseEventService

_PROFILE_TABLE = "context_engine_context_profile"
_POLICY_TABLE = "context_engine_context_policy"
_CONTRIBUTOR_BINDING_TABLE = "context_engine_context_contributor_binding"
_SOURCE_BINDING_TABLE = "context_engine_context_source_binding"
_TRACE_POLICY_TABLE = "context_engine_context_trace_policy"
_STATE_TABLE = "context_engine_context_state_snapshot"
_EVENT_TABLE = "context_engine_context_event_log"
_MEMORY_TABLE = "context_engine_context_memory_record"
_CACHE_TABLE = "context_engine_context_cache_record"
_TRACE_TABLE = "context_engine_context_trace"
_KNOWLEDGE_SCOPE_TABLE = "knowledge_pack_knowledge_scope"
_CONVERSATION_STATE_TABLE = "channel_orchestration_conversation_state"
_WORK_ITEM_TABLE = "channel_orchestration_work_item"
_CASE_TABLE = "ops_case_case"
_CASE_EVENT_TABLE = "ops_case_case_event"
_AUDIT_TRACE_TABLE = "audit_biz_trace_event"


def _config_provider():
    return di.container.config


def _rsg_provider():
    return di.container.relational_storage_gateway


class ContextEngineFWExtension(IFWExtension):  # pylint: disable=too-few-public-methods
    """Register plugin-owned context runtime components."""

    def __init__(
        self,
        config_provider=_config_provider,
        rsg_provider=_rsg_provider,
    ) -> None:
        self._config: SimpleNamespace = config_provider()
        self._rsg: IRelationalStorageGateway = rsg_provider()

    @property
    def platforms(self) -> list[str]:
        return []

    async def setup(self, app: Quart) -> None:  # noqa: ARG002
        self._register_runtime_tables()

        profile_service = ContextProfileService(table=_PROFILE_TABLE, rsg=self._rsg)
        policy_service = ContextPolicyService(table=_POLICY_TABLE, rsg=self._rsg)
        contributor_binding_service = ContextContributorBindingService(
            table=_CONTRIBUTOR_BINDING_TABLE,
            rsg=self._rsg,
        )
        source_binding_service = ContextSourceBindingService(
            table=_SOURCE_BINDING_TABLE,
            rsg=self._rsg,
        )
        trace_policy_service = ContextTracePolicyService(
            table=_TRACE_POLICY_TABLE,
            rsg=self._rsg,
        )

        snapshot_service = ContextStateSnapshotService(table=_STATE_TABLE, rsg=self._rsg)
        event_log_service = ContextEventLogService(table=_EVENT_TABLE, rsg=self._rsg)
        memory_service = ContextMemoryRecordService(table=_MEMORY_TABLE, rsg=self._rsg)
        cache_service = ContextCacheRecordService(table=_CACHE_TABLE, rsg=self._rsg)
        trace_service = ContextTraceService(table=_TRACE_TABLE, rsg=self._rsg)

        knowledge_scope_service = KnowledgeScopeService(
            table=_KNOWLEDGE_SCOPE_TABLE,
            rsg=self._rsg,
        )
        conversation_state_service = ConversationStateService(
            table=_CONVERSATION_STATE_TABLE,
            rsg=self._rsg,
        )
        work_item_service = WorkItemService(table=_WORK_ITEM_TABLE, rsg=self._rsg)
        case_service = CaseService(table=_CASE_TABLE, rsg=self._rsg)
        case_event_service = CaseEventService(table=_CASE_EVENT_TABLE, rsg=self._rsg)
        audit_trace_service = AuditBizTraceEventService(
            table=_AUDIT_TRACE_TABLE,
            rsg=self._rsg,
        )

        registry = ContextComponentRegistry()
        registry.set_policy_resolver(
            DefaultContextPolicyResolver(
                profile_service=profile_service,
                policy_service=policy_service,
                contributor_binding_service=contributor_binding_service,
                source_binding_service=source_binding_service,
                trace_policy_service=trace_policy_service,
            )
        )
        registry.set_state_store(
            RelationalContextStateStore(
                snapshot_service=snapshot_service,
                event_log_service=event_log_service,
            )
        )
        registry.set_memory_writer(DefaultMemoryWriter(memory_service=memory_service))
        registry.set_cache(RelationalContextCache(cache_service=cache_service))
        registry.register_trace_sink(
            RelationalContextTraceSink(
                trace_service=trace_service,
                audit_trace_service=audit_trace_service,
            )
        )

        registry.register_guard(DefaultContextGuard())
        registry.register_ranker(DefaultContextRanker())
        registry.register_contributor(PersonaPolicyContributor(config=self._config))
        registry.register_contributor(StateContributor())
        registry.register_contributor(
            ChannelOrchestrationContributor(
                conversation_state_service=conversation_state_service,
                work_item_service=work_item_service,
            )
        )
        registry.register_contributor(
            OpsCaseContributor(
                case_service=case_service,
                case_event_service=case_event_service,
            )
        )
        registry.register_contributor(
            KnowledgePackContributor(knowledge_scope_service=knowledge_scope_service)
        )
        registry.register_contributor(MemoryContributor(memory_service=memory_service))
        registry.register_contributor(
            AuditContributor(audit_trace_service=audit_trace_service)
        )
        registry.register_contributor(
            RecentTurnContributor(event_log_service=event_log_service)
        )

        di.container.register_ext_service(
            di.EXT_SERVICE_CONTEXT_COMPONENT_REGISTRY,
            registry,
            override=True,
        )

        # Import endpoints now that runtime services exist.
        # pylint: disable=import-outside-toplevel, unused-import
        import mugen.core.plugin.context_engine.api  # noqa: F401

    def _register_runtime_tables(self) -> None:
        if not isinstance(self._rsg, SQLAlchemyRelationalStorageGateway):
            return
        try:
            self._rsg.register_tables(
                {
                    _STATE_TABLE: ContextStateSnapshot.__table__,
                    _EVENT_TABLE: ContextEventLog.__table__,
                    _MEMORY_TABLE: ContextMemoryRecord.__table__,
                    _CACHE_TABLE: ContextCacheRecord.__table__,
                    _TRACE_TABLE: ContextTrace.__table__,
                }
            )
        except ValueError:
            return

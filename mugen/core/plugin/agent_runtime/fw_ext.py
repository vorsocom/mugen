"""Framework extension for agent_runtime runtime registration."""

from __future__ import annotations

__all__ = ["AgentRuntimeFWExtension"]

from types import SimpleNamespace

from quart import Quart

from mugen.core import di
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.contract.gateway.storage.rdbms import IRelationalStorageGateway
from mugen.core.gateway.storage.rdbms.sqla.sqla_gateway import (
    SQLAlchemyRelationalStorageGateway,
)
from mugen.core.plugin.agent_runtime.model import AgentPlanRun, AgentPlanStep
from mugen.core.plugin.agent_runtime.service import (
    ACPActionCapabilityProvider,
    AgentComponentRegistry,
    AgentPlanRunService,
    AgentPlanStepService,
    AllowlistExecutionGuard,
    CodeConfiguredAgentPolicyResolver,
    LLMEvaluationStrategy,
    LLMPlannerStrategy,
    RelationalAgentScheduler,
    RelationalPlanRunStore,
    TextResponseSynthesizer,
)

_PLAN_RUN_TABLE = "agent_runtime_plan_run"
_PLAN_STEP_TABLE = "agent_runtime_plan_step"


def _config_provider():
    return di.container.config


def _rsg_provider():
    return di.container.relational_storage_gateway


class AgentRuntimeFWExtension(IFWExtension):  # pylint: disable=too-few-public-methods
    """Register plugin-owned agent-runtime components."""

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

        run_service = AgentPlanRunService(table=_PLAN_RUN_TABLE, rsg=self._rsg)
        step_service = AgentPlanStepService(table=_PLAN_STEP_TABLE, rsg=self._rsg)

        run_store = RelationalPlanRunStore(
            run_service=run_service,
            step_service=step_service,
        )
        registry = AgentComponentRegistry()
        owner = "agent_runtime.plugin"
        registry.set_policy_resolver(
            CodeConfiguredAgentPolicyResolver(config=self._config),
            owner=owner,
        )
        registry.set_run_store(run_store, owner=owner)
        registry.set_scheduler(
            RelationalAgentScheduler(run_store=run_store),
            owner=owner,
        )
        registry.register_planner(
            LLMPlannerStrategy(
                completion_gateway=di.container.completion_gateway,
                logging_gateway=di.container.logging_gateway,
            )
        )
        registry.register_evaluator(
            LLMEvaluationStrategy(
                completion_gateway=di.container.completion_gateway,
                logging_gateway=di.container.logging_gateway,
            )
        )
        registry.register_capability_provider(
            ACPActionCapabilityProvider(
                admin_registry=di.container.get_ext_service(
                    di.EXT_SERVICE_ADMIN_REGISTRY,
                    None,
                ),
                logging_gateway=di.container.logging_gateway,
            )
        )
        registry.register_execution_guard(AllowlistExecutionGuard())
        registry.register_response_synthesizer(TextResponseSynthesizer())

        di.container.register_ext_service(
            di.EXT_SERVICE_AGENT_COMPONENT_REGISTRY,
            registry,
            override=True,
        )

        # pylint: disable=import-outside-toplevel, unused-import
        import mugen.core.plugin.agent_runtime.api  # noqa: F401

    def _register_runtime_tables(self) -> None:
        if not isinstance(self._rsg, SQLAlchemyRelationalStorageGateway):
            return
        try:
            self._rsg.register_tables(
                {
                    _PLAN_RUN_TABLE: AgentPlanRun.__table__,
                    _PLAN_STEP_TABLE: AgentPlanStep.__table__,
                }
            )
        except ValueError:
            return

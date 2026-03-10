"""Tests for the agent-runtime component registry."""

from __future__ import annotations

import unittest

from mugen.core.plugin.agent_runtime.service.registry import AgentComponentRegistry


class TestMugenAgentRuntimeRegistry(unittest.TestCase):
    """Exercise multi-register and single-owner behavior."""

    def test_multi_registers_append_components(self) -> None:
        registry = AgentComponentRegistry()

        registry.register_planner("planner")
        registry.register_evaluator("evaluator")
        registry.register_capability_provider("provider")
        registry.register_execution_guard("guard")
        registry.register_response_synthesizer("synth")
        registry.register_trace_sink("trace")

        self.assertEqual(registry.planners, ["planner"])
        self.assertEqual(registry.evaluators, ["evaluator"])
        self.assertEqual(registry.capability_providers, ["provider"])
        self.assertEqual(registry.execution_guards, ["guard"])
        self.assertEqual(registry.response_synthesizers, ["synth"])
        self.assertEqual(registry.trace_sinks, ["trace"])

    def test_single_slot_owner_conflict_raises(self) -> None:
        registry = AgentComponentRegistry()

        registry.set_run_store("first", owner="plugin.one")

        with self.assertRaisesRegex(RuntimeError, "already has 'run_store'"):
            registry.set_run_store("second", owner="plugin.two")


if __name__ == "__main__":
    unittest.main()

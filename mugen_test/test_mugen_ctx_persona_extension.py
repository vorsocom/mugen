"""Unit tests for the persona-policy context contributor."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from mugen.core.contract.context import ContextPolicy, ContextScope, ContextTurnRequest
from mugen.core.plugin.context_engine.service.contributor import PersonaPolicyContributor


def _request(*, persona: str | None = None) -> tuple[PersonaPolicyContributor, ContextTurnRequest]:
    assistant_cfg = (
        SimpleNamespace(persona=persona) if persona is not None else SimpleNamespace()
    )
    contributor = PersonaPolicyContributor(
        config=SimpleNamespace(mugen=SimpleNamespace(assistant=assistant_cfg))
    )
    request = ContextTurnRequest(
        scope=ContextScope(
            tenant_id="tenant-1",
            platform="matrix",
            channel_id="matrix",
            room_id="room-1",
            sender_id="user-1",
            conversation_id="room-1",
        ),
        user_message="hello",
        ingress_metadata={
            "tenant_resolution": {
                "mode": "resolved",
                "reason_code": None,
                "source": "test",
            }
        },
    )
    return contributor, request


class TestPersonaPolicyContributor(unittest.IsolatedAsyncioTestCase):
    """Covers persona compilation into the first system lane."""

    async def test_collect_handles_missing_persona(self) -> None:
        contributor, request = _request()

        candidates = await contributor.collect(
            request,
            policy=ContextPolicy(),
            state=None,
        )

        self.assertEqual(len(candidates), 1)
        artifact = candidates[0].artifact
        self.assertEqual(artifact.lane, "system_persona_policy")
        self.assertIsNone(artifact.content["persona"])

    async def test_collect_includes_configured_persona_and_tenant_resolution(self) -> None:
        contributor, request = _request(persona="Be concise.")

        candidates = await contributor.collect(
            request,
            policy=ContextPolicy(policy_key="default-policy"),
            state=None,
        )

        self.assertEqual(len(candidates), 1)
        artifact = candidates[0].artifact
        self.assertEqual(artifact.content["persona"], "Be concise.")
        self.assertEqual(artifact.content["policy_key"], "default-policy")
        self.assertEqual(
            artifact.content["tenant_resolution"],
            request.ingress_metadata["tenant_resolution"],
        )

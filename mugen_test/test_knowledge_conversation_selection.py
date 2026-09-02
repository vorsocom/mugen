"""Tests safe conversational selection for approved Knowledge Pack results."""

from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import Mock
import uuid

from mugen.core.contract.gateway.completion import (
    CompletionRequest,
    CompletionResponse,
    CompletionToolCall,
    ICompletionGateway,
)
from mugen.core.plugin.knowledge_pack.contract.service import (
    ApprovedKnowledgeResult,
    IKnowledgeConversationSelector,
    KnowledgeConversationCandidate,
    KnowledgeConversationDecisionType,
    KnowledgeConversationSelection,
    KnowledgeConversationSelectionPolicy,
    KnowledgeConversationSelectionProvenance,
)
from mugen.core.plugin.knowledge_pack.service import KnowledgeConversationSelector


def _result(
    similarity: float | None = 0.8,
    *,
    service_profile_id: uuid.UUID | None = None,
    **changes,
) -> ApprovedKnowledgeResult:
    values = {
        "tenant_id": uuid.uuid4(),
        "knowledge_pack_id": uuid.uuid4(),
        "knowledge_pack_version_id": uuid.uuid4(),
        "knowledge_entry_id": uuid.uuid4(),
        "knowledge_entry_revision_id": uuid.uuid4(),
        "knowledge_scope_id": uuid.uuid4(),
        "entry_key": "refund-policy",
        "title": "Refund policy",
        "body": "Approved relational answer",
        "body_json": None,
        "channel": "whatsapp",
        "locale": "en-US",
        "category": "billing",
        "service_route_key": "customer-care",
        "client_profile_key": "retail",
        "service_profile_id": service_profile_id,
        "similarity": similarity,
        "distance": None if similarity is None else 1.0 - similarity,
        "projection_provider": "pgvector",
        "projection_target_fingerprint": "f" * 64,
        **changes,
    }
    return ApprovedKnowledgeResult(**values)


def _candidate(
    similarity: float | None = 0.8,
    *,
    candidate_id: uuid.UUID | None = None,
    result: ApprovedKnowledgeResult | None = None,
    service_profile_id: uuid.UUID | None = None,
) -> KnowledgeConversationCandidate:
    return KnowledgeConversationCandidate(
        candidate_id=candidate_id or uuid.uuid4(),
        result=result or _result(similarity, service_profile_id=service_profile_id),
    )


def _policy(**changes) -> KnowledgeConversationSelectionPolicy:
    values = {
        "auto_answer_min_similarity": 0.9,
        "adjudication_min_similarity": 0.7,
        "winner_margin": 0.05,
        "candidate_limit": 5,
        "max_answers": 1,
        "llm_adjudication_enabled": True,
        **changes,
    }
    return KnowledgeConversationSelectionPolicy(**values)


def _tool_response(
    *,
    decision: str = "answer",
    candidate_ids: list[object] | None = None,
    name: str = "select_knowledge_candidates",
) -> CompletionResponse:
    return CompletionResponse(
        content="Generated prose that must never reach the selector output.",
        tool_calls=[
            CompletionToolCall(
                id="call-1",
                name=name,
                arguments={
                    "decision": decision,
                    "candidate_ids": candidate_ids or [],
                },
            )
        ],
    )


class _CompletionGateway(ICompletionGateway):
    def __init__(
        self,
        response: CompletionResponse | object | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or CompletionResponse(content=None)
        self.error = error
        self.requests: list[CompletionRequest] = []

    async def check_readiness(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def get_completion(self, request: CompletionRequest) -> CompletionResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response  # type: ignore[return-value]


class TestKnowledgeConversationContracts(unittest.TestCase):
    """Covers contract validation, approval state, and public exports."""

    def test_approved_result_and_candidate_validation(self) -> None:
        result = _result(0.8, body=None, body_json={"answer": "approved"})
        self.assertTrue(result.approved_for_selection)
        self.assertEqual(result.similarity, 0.8)
        self.assertAlmostEqual(result.distance or 0.0, 0.2)
        candidate = _candidate(result=result)
        provenance = KnowledgeConversationSelectionProvenance.from_candidate(candidate)
        self.assertEqual(provenance.knowledge_pack_id, result.knowledge_pack_id)

        with self.assertRaises(TypeError):
            _candidate(candidate_id="bad")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            KnowledgeConversationCandidate(
                candidate_id=uuid.uuid4(),
                result=Mock(),  # type: ignore[arg-type]
            )
        unpublished = _result(knowledge_pack_version_status="approved")
        self.assertFalse(unpublished.approved_for_selection)
        with self.assertRaisesRegex(ValueError, "not approved"):
            _candidate(result=unpublished)

    def test_approved_result_rejects_malformed_authority_data(self) -> None:
        valid = _result()
        for field_name, value, error_type in (
            ("tenant_id", "bad", TypeError),
            ("service_profile_id", "bad", TypeError),
            ("entry_key", " ", ValueError),
            ("body_json", "bad", TypeError),
            ("similarity", True, TypeError),
            ("similarity", 2.0, ValueError),
            ("distance", True, TypeError),
            ("distance", -1.0, ValueError),
        ):
            with self.subTest(field_name=field_name), self.assertRaises(error_type):
                replace(valid, **{field_name: value})
        with self.assertRaises(ValueError):
            replace(valid, body=None, body_json=None)

    def test_policy_validation(self) -> None:
        policy = _policy(
            auto_answer_min_similarity=1,
            adjudication_min_similarity=0,
            winner_margin=0,
        )
        self.assertEqual(policy.auto_answer_min_similarity, 1.0)
        for changes, error_type in (
            ({"auto_answer_min_similarity": True}, TypeError),
            ({"winner_margin": -1}, ValueError),
            (
                {
                    "auto_answer_min_similarity": 0.5,
                    "adjudication_min_similarity": 0.6,
                },
                ValueError,
            ),
            ({"candidate_limit": True}, ValueError),
            ({"candidate_limit": 1.5}, ValueError),
            ({"candidate_limit": 0}, ValueError),
            ({"max_answers": True}, ValueError),
            ({"max_answers": 1.5}, ValueError),
            ({"max_answers": 0}, ValueError),
            ({"max_answers": 4}, ValueError),
            ({"candidate_limit": 1, "max_answers": 2}, ValueError),
            ({"llm_adjudication_enabled": 1}, TypeError),
        ):
            with self.subTest(changes=changes), self.assertRaises(error_type):
                _policy(**changes)

    def test_selection_validation(self) -> None:
        candidate = _candidate()
        provenance = KnowledgeConversationSelectionProvenance.from_candidate(candidate)
        values = {
            "decision_type": KnowledgeConversationDecisionType.ANSWER,
            "selected_candidate_ids": (candidate.candidate_id,),
            "selected_provenance": (provenance,),
            "semantic_retrieval_used": True,
            "llm_adjudication_used": False,
            "reason_code": "test",
        }
        selection = KnowledgeConversationSelection(**values)
        self.assertEqual(selection.selected_candidate_ids, (candidate.candidate_id,))
        invalid_cases = (
            ({"decision_type": "answer"}, TypeError),
            (
                {
                    "selected_candidate_ids": (),
                    "selected_provenance": (),
                },
                ValueError,
            ),
            (
                {
                    "decision_type": KnowledgeConversationDecisionType.CLARIFY,
                },
                ValueError,
            ),
            ({"selected_provenance": ()}, ValueError),
            (
                {
                    "selected_provenance": (
                        replace(provenance, candidate_id=uuid.uuid4()),
                    )
                },
                ValueError,
            ),
            (
                {
                    "selected_candidate_ids": ("bad",),
                    "selected_provenance": (replace(provenance, candidate_id="bad"),),
                },
                TypeError,
            ),
            ({"semantic_retrieval_used": 1}, TypeError),
            ({"llm_adjudication_used": 0}, TypeError),
            ({"reason_code": " "}, ValueError),
        )
        for changes, error_type in invalid_cases:
            with self.subTest(changes=changes), self.assertRaises(error_type):
                KnowledgeConversationSelection(**{**values, **changes})

    def test_selector_implements_stable_interface(self) -> None:
        selector = KnowledgeConversationSelector()
        self.assertIsInstance(selector, IKnowledgeConversationSelector)


class TestKnowledgeConversationDeterministicSelection(unittest.IsolatedAsyncioTestCase):
    """Covers clear winners, multiple answers, margins, and fail-safe fallbacks."""

    async def test_clear_winner_bypasses_unavailable_completion(self) -> None:
        gateway = _CompletionGateway(error=RuntimeError("offline"))
        first = _candidate(0.96)
        decision = await KnowledgeConversationSelector(gateway).select(
            query_text="Can I get a refund?",
            candidates=(first,),
            policy=_policy(),
        )
        self.assertEqual(
            decision.decision_type,
            KnowledgeConversationDecisionType.ANSWER,
        )
        self.assertEqual(decision.selected_candidate_ids, (first.candidate_id,))
        self.assertTrue(decision.semantic_retrieval_used)
        self.assertFalse(decision.llm_adjudication_used)
        self.assertEqual(decision.reason_code, "deterministic_similarity_winner")
        self.assertEqual(gateway.requests, [])

    async def test_multiple_answers_preserve_provenance(self) -> None:
        service_profile_id = uuid.uuid4()
        first = _candidate(0.98, service_profile_id=service_profile_id)
        second = _candidate(0.96, service_profile_id=service_profile_id)
        third = _candidate(0.7, service_profile_id=service_profile_id)
        decision = await KnowledgeConversationSelector().select(
            query_text="Tell me the applicable policies",
            candidates=(third, second, first),
            policy=_policy(max_answers=3),
        )
        self.assertEqual(
            decision.selected_candidate_ids,
            (first.candidate_id, second.candidate_id),
        )
        self.assertEqual(
            [item.service_profile_id for item in decision.selected_provenance],
            [service_profile_id, service_profile_id],
        )
        self.assertFalse(hasattr(decision, "content"))
        self.assertFalse(hasattr(decision.selected_provenance[0], "body"))

    async def test_winner_margin_controls_deterministic_boundary(self) -> None:
        first = _candidate(0.95)
        second = _candidate(0.93)
        selector = KnowledgeConversationSelector()
        ambiguous = await selector.select(
            query_text="policy",
            candidates=(first, second),
            policy=_policy(
                winner_margin=0.03,
                llm_adjudication_enabled=False,
            ),
        )
        self.assertEqual(
            ambiguous.decision_type,
            KnowledgeConversationDecisionType.CLARIFY,
        )
        self.assertEqual(ambiguous.reason_code, "llm_adjudication_disabled")
        clear = await selector.select(
            query_text="policy",
            candidates=(first, second),
            policy=_policy(
                winner_margin=0.01,
                llm_adjudication_enabled=False,
            ),
        )
        self.assertEqual(clear.selected_candidate_ids, (first.candidate_id,))

    async def test_declines_when_no_candidate_reaches_adjudication_floor(self) -> None:
        decision = await KnowledgeConversationSelector().select(
            query_text="unrelated",
            candidates=(_candidate(None), _candidate(0.5)),
            policy=_policy(),
        )
        self.assertEqual(
            decision.decision_type,
            KnowledgeConversationDecisionType.DECLINE,
        )
        self.assertEqual(decision.reason_code, "no_acceptable_candidate")
        self.assertEqual(decision.selected_candidate_ids, ())

    async def test_gray_zone_without_gateway_is_explicitly_unavailable(self) -> None:
        decision = await KnowledgeConversationSelector().select(
            query_text="possibly relevant",
            candidates=(_candidate(0.8),),
            policy=_policy(),
        )
        self.assertEqual(
            decision.decision_type,
            KnowledgeConversationDecisionType.UNAVAILABLE,
        )
        self.assertFalse(decision.llm_adjudication_used)
        self.assertEqual(decision.reason_code, "completion_gateway_unavailable")

    async def test_completion_error_fails_closed(self) -> None:
        gateway = _CompletionGateway(error=RuntimeError("offline"))
        decision = await KnowledgeConversationSelector(gateway).select(
            query_text="possibly relevant",
            candidates=(_candidate(0.8),),
            policy=_policy(),
        )
        self.assertEqual(
            decision.decision_type,
            KnowledgeConversationDecisionType.UNAVAILABLE,
        )
        self.assertTrue(decision.llm_adjudication_used)
        self.assertEqual(decision.reason_code, "completion_gateway_error")

    async def test_input_contract_rejects_invalid_candidate_sets(self) -> None:
        selector = KnowledgeConversationSelector()
        candidate = _candidate()
        cases = (
            {
                "query_text": None,
                "candidates": (),
                "policy": _policy(),
            },
            {
                "query_text": " ",
                "candidates": (),
                "policy": _policy(),
            },
            {
                "query_text": "x",
                "candidates": (),
                "policy": Mock(),
            },
            {
                "query_text": "x",
                "candidates": [],
                "policy": _policy(),
            },
            {
                "query_text": "x",
                "candidates": (Mock(),),
                "policy": _policy(),
            },
            {
                "query_text": "x",
                "candidates": (candidate, candidate),
                "policy": _policy(),
            },
            {
                "query_text": "x",
                "candidates": (
                    candidate,
                    _candidate(result=candidate.result),
                ),
                "policy": _policy(),
            },
        )
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(
                (TypeError, ValueError)
            ):
                await selector.select(**kwargs)  # type: ignore[arg-type]


class TestKnowledgeConversationCompletionAdjudication(unittest.IsolatedAsyncioTestCase):
    """Covers constrained decisions and hostile or malformed completion output."""

    async def test_llm_selects_only_ids_and_request_is_provider_neutral(self) -> None:
        first = _candidate(0.85)
        second = _candidate(0.84)
        gateway = _CompletionGateway(
            _tool_response(
                candidate_ids=[str(second.candidate_id), str(first.candidate_id)]
            )
        )
        decision = await KnowledgeConversationSelector(gateway).select(
            query_text="Which approved answers apply?",
            candidates=(second, first),
            policy=_policy(max_answers=2),
        )
        self.assertEqual(
            decision.decision_type,
            KnowledgeConversationDecisionType.ANSWER,
        )
        self.assertEqual(
            decision.selected_candidate_ids,
            (first.candidate_id, second.candidate_id),
        )
        self.assertTrue(decision.llm_adjudication_used)
        self.assertEqual(decision.reason_code, "llm_selected_candidates")
        request = gateway.requests[0]
        self.assertEqual(request.operation, "knowledge_conversation_selection")
        self.assertEqual(request.vendor_params, {})
        self.assertEqual(len(request.tools), 1)
        self.assertTrue(request.tools[0].strict)
        self.assertNotIn("Generated prose", repr(decision))

    async def test_llm_can_request_clarification_or_decline(self) -> None:
        for outcome, decision_type in (
            ("clarify", KnowledgeConversationDecisionType.CLARIFY),
            ("decline", KnowledgeConversationDecisionType.DECLINE),
        ):
            gateway = _CompletionGateway(_tool_response(decision=outcome))
            decision = await KnowledgeConversationSelector(gateway).select(
                query_text="ambiguous",
                candidates=(_candidate(0.8),),
                policy=_policy(),
            )
            with self.subTest(outcome=outcome):
                self.assertEqual(decision.decision_type, decision_type)
                self.assertEqual(decision.reason_code, f"llm_{outcome}")

    async def test_completion_revalidates_candidate_limit(self) -> None:
        first = _candidate(0.85)
        excluded = _candidate(0.84)
        gateway = _CompletionGateway(
            _tool_response(candidate_ids=[str(excluded.candidate_id)])
        )
        decision = await KnowledgeConversationSelector(gateway).select(
            query_text="ambiguous",
            candidates=(first, excluded),
            policy=_policy(candidate_limit=1),
        )
        self.assertEqual(
            decision.decision_type,
            KnowledgeConversationDecisionType.UNAVAILABLE,
        )
        self.assertEqual(decision.reason_code, "completion_invalid_candidate_ids")
        self.assertNotIn(
            str(excluded.candidate_id),
            gateway.requests[0].messages[1].content,
        )

    async def test_malformed_completion_output_fails_closed(self) -> None:
        candidate = _candidate(0.8)
        unknown_id = uuid.uuid4()
        cases = (
            object(),
            CompletionResponse(content=None, tool_calls=[]),
            CompletionResponse(content=None, tool_calls=[object()]),
            CompletionResponse(content=None, tool_calls=[{"name": 1}]),
            _tool_response(name="wrong_tool"),
            CompletionResponse(
                content=None,
                tool_calls=[
                    CompletionToolCall(
                        id=None,
                        name="select_knowledge_candidates",
                        arguments={
                            "decision": "answer",
                            "candidate_ids": [str(candidate.candidate_id)],
                            "extra": True,
                        },
                    )
                ],
            ),
            _tool_response(decision="write_prose"),
            CompletionResponse(
                content=None,
                tool_calls=[
                    CompletionToolCall(
                        id=None,
                        name="select_knowledge_candidates",
                        arguments={"decision": "answer", "candidate_ids": "bad"},
                    )
                ],
            ),
        )
        for response in cases:
            gateway = _CompletionGateway(response)
            decision = await KnowledgeConversationSelector(gateway).select(
                query_text="ambiguous",
                candidates=(candidate,),
                policy=_policy(),
            )
            with self.subTest(response=response):
                self.assertEqual(
                    decision.decision_type,
                    KnowledgeConversationDecisionType.UNAVAILABLE,
                )
                self.assertEqual(
                    decision.reason_code,
                    "completion_malformed_output",
                )

        invalid_id_cases = (
            _tool_response(
                decision="clarify",
                candidate_ids=[str(candidate.candidate_id)],
            ),
            _tool_response(candidate_ids=[]),
            _tool_response(
                candidate_ids=[str(candidate.candidate_id), str(unknown_id)]
            ),
            _tool_response(candidate_ids=[1]),
            _tool_response(candidate_ids=["not-a-uuid"]),
            _tool_response(
                candidate_ids=[str(candidate.candidate_id), str(candidate.candidate_id)]
            ),
            _tool_response(candidate_ids=[str(unknown_id)]),
        )
        for response in invalid_id_cases:
            gateway = _CompletionGateway(response)
            decision = await KnowledgeConversationSelector(gateway).select(
                query_text="ambiguous",
                candidates=(candidate,),
                policy=_policy(),
            )
            with self.subTest(response=response):
                self.assertEqual(
                    decision.decision_type,
                    KnowledgeConversationDecisionType.UNAVAILABLE,
                )
                self.assertEqual(
                    decision.reason_code,
                    "completion_invalid_candidate_ids",
                )

        duplicate_response = _tool_response(
            candidate_ids=[str(candidate.candidate_id), str(candidate.candidate_id)]
        )
        duplicate_decision = await KnowledgeConversationSelector(
            _CompletionGateway(duplicate_response)
        ).select(
            query_text="ambiguous",
            candidates=(candidate,),
            policy=_policy(max_answers=2),
        )
        self.assertEqual(
            duplicate_decision.reason_code,
            "completion_invalid_candidate_ids",
        )

    async def test_dict_tool_call_is_normalized(self) -> None:
        candidate = _candidate(0.8)
        response = CompletionResponse(
            content=None,
            tool_calls=[
                {
                    "id": "call-1",
                    "name": "select_knowledge_candidates",
                    "arguments": {
                        "decision": "answer",
                        "candidate_ids": [str(candidate.candidate_id)],
                    },
                }
            ],
        )
        decision = await KnowledgeConversationSelector(
            _CompletionGateway(response)
        ).select(
            query_text="ambiguous",
            candidates=(candidate,),
            policy=_policy(),
        )
        self.assertEqual(decision.selected_candidate_ids, (candidate.candidate_id,))

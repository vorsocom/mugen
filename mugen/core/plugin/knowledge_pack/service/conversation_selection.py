"""Safe deterministic and completion-assisted Knowledge Pack selection."""

from __future__ import annotations

__all__ = ["KnowledgeConversationSelector"]

import json
from typing import Any
import uuid

from mugen.core.contract.gateway.completion import (
    CompletionInferenceConfig,
    CompletionMessage,
    CompletionRequest,
    CompletionResponse,
    CompletionTool,
    CompletionToolCall,
    ICompletionGateway,
)
from mugen.core.plugin.knowledge_pack.contract.service.knowledge_conversation import (
    IKnowledgeConversationSelector,
    KnowledgeConversationCandidate,
    KnowledgeConversationDecisionType,
    KnowledgeConversationSelection,
    KnowledgeConversationSelectionPolicy,
    KnowledgeConversationSelectionProvenance,
)

_ADJUDICATION_TOOL_NAME = "select_knowledge_candidates"


class KnowledgeConversationSelector(
    IKnowledgeConversationSelector
):  # pylint: disable=too-few-public-methods
    """Select approved answers while treating completion as an optional judge."""

    def __init__(self, completion_gateway: ICompletionGateway | None = None) -> None:
        self._completion_gateway = completion_gateway

    @staticmethod
    def _ranked_candidates(
        candidates: tuple[KnowledgeConversationCandidate, ...],
        policy: KnowledgeConversationSelectionPolicy,
    ) -> tuple[KnowledgeConversationCandidate, ...]:
        ranked = sorted(
            candidates,
            key=lambda item: (
                -(
                    item.result.similarity
                    if item.result.similarity is not None
                    else -1.0
                ),
                str(item.candidate_id),
            ),
        )
        return tuple(ranked[: policy.candidate_limit])

    @staticmethod
    def _validate_candidates(
        candidates: tuple[KnowledgeConversationCandidate, ...],
    ) -> None:
        if not isinstance(candidates, tuple):
            raise TypeError("candidates must be a tuple.")
        candidate_ids: set[uuid.UUID] = set()
        provenance_keys: set[tuple[uuid.UUID, ...]] = set()
        for candidate in candidates:
            if not isinstance(candidate, KnowledgeConversationCandidate):
                raise TypeError(
                    "candidates must contain KnowledgeConversationCandidate values."
                )
            if candidate.candidate_id in candidate_ids:
                raise ValueError("candidate IDs must be unique.")
            candidate_ids.add(candidate.candidate_id)
            result = candidate.result
            provenance_key = (
                result.tenant_id,
                result.knowledge_pack_id,
                result.knowledge_pack_version_id,
                result.knowledge_entry_id,
                result.knowledge_entry_revision_id,
                result.knowledge_scope_id,
            )
            if provenance_key in provenance_keys:
                raise ValueError("candidate relational provenance must be unique.")
            provenance_keys.add(provenance_key)

    @staticmethod
    def _eligible_candidates(
        candidates: tuple[KnowledgeConversationCandidate, ...],
        minimum_similarity: float,
    ) -> tuple[KnowledgeConversationCandidate, ...]:
        return tuple(
            candidate
            for candidate in candidates
            if candidate.result.similarity is not None
            and candidate.result.similarity >= minimum_similarity
        )

    @classmethod
    def _deterministic_winners(
        cls,
        candidates: tuple[KnowledgeConversationCandidate, ...],
        policy: KnowledgeConversationSelectionPolicy,
    ) -> tuple[KnowledgeConversationCandidate, ...]:
        auto_candidates = cls._eligible_candidates(
            candidates,
            policy.auto_answer_min_similarity,
        )
        if not auto_candidates:
            return ()
        selected = auto_candidates[: policy.max_answers]
        selected_ids = {item.candidate_id for item in selected}
        competing = next(
            (
                candidate
                for candidate in candidates
                if candidate.candidate_id not in selected_ids
                and candidate.result.similarity is not None
                and candidate.result.similarity >= policy.adjudication_min_similarity
            ),
            None,
        )
        if competing is None:
            return selected
        selected_floor = selected[-1].result.similarity
        if selected_floor - competing.result.similarity < policy.winner_margin:
            return ()
        return selected

    @staticmethod
    def _selection(
        *,
        decision_type: KnowledgeConversationDecisionType,
        selected: tuple[KnowledgeConversationCandidate, ...] = (),
        llm_adjudication_used: bool,
        reason_code: str,
    ) -> KnowledgeConversationSelection:
        return KnowledgeConversationSelection(
            decision_type=decision_type,
            selected_candidate_ids=tuple(item.candidate_id for item in selected),
            selected_provenance=tuple(
                KnowledgeConversationSelectionProvenance.from_candidate(item)
                for item in selected
            ),
            semantic_retrieval_used=True,
            llm_adjudication_used=llm_adjudication_used,
            reason_code=reason_code,
        )

    @staticmethod
    def _candidate_payload(
        candidate: KnowledgeConversationCandidate,
    ) -> dict[str, Any]:
        result = candidate.result
        return {
            "candidate_id": str(candidate.candidate_id),
            "title": result.title,
            "body": result.body,
            "body_json": result.body_json,
            "similarity": result.similarity,
            "scope": {
                "channel": result.channel,
                "locale": result.locale,
                "category": result.category,
                "service_route_key": result.service_route_key,
                "client_profile_key": result.client_profile_key,
                "service_profile_id": (
                    None
                    if result.service_profile_id is None
                    else str(result.service_profile_id)
                ),
            },
        }

    @classmethod
    def _completion_request(
        cls,
        *,
        query_text: str,
        candidates: tuple[KnowledgeConversationCandidate, ...],
        max_answers: int,
    ) -> CompletionRequest:
        tool = CompletionTool(
            name=_ADJUDICATION_TOOL_NAME,
            description=(
                "Select supplied approved candidate IDs, request clarification, "
                "or decline all candidates. Do not generate response prose."
            ),
            strict=True,
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "decision": {
                        "type": "string",
                        "enum": ["answer", "clarify", "decline"],
                    },
                    "candidate_ids": {
                        "type": "array",
                        "items": {"type": "string", "format": "uuid"},
                        "maxItems": max_answers,
                    },
                },
                "required": ["decision", "candidate_ids"],
            },
        )
        payload = {
            "query_text": query_text,
            "candidates": [cls._candidate_payload(item) for item in candidates],
            "constraints": {
                "maximum_answers": max_answers,
                "allowed_decisions": ["answer", "clarify", "decline"],
                "customer_facing_prose_forbidden": True,
            },
        }
        return CompletionRequest(
            operation="knowledge_conversation_selection",
            messages=[
                CompletionMessage(
                    role="system",
                    content=(
                        "Adjudicate only the supplied approved knowledge candidates. "
                        "Call the supplied tool exactly once. Never write an answer, "
                        "explanation, clarification question, or other customer-facing "
                        "prose."
                    ),
                ),
                CompletionMessage(
                    role="user",
                    content=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                ),
            ],
            inference=CompletionInferenceConfig(
                max_completion_tokens=256,
                temperature=0.0,
                stream=False,
            ),
            tools=[tool],
        )

    @staticmethod
    def _normalized_tool_call(
        response: CompletionResponse,
    ) -> CompletionToolCall | None:
        if (
            not isinstance(response, CompletionResponse)
            or len(response.tool_calls) != 1
        ):
            return None
        raw_call = response.tool_calls[0]
        if isinstance(raw_call, CompletionToolCall):
            return raw_call
        if not isinstance(raw_call, dict):
            return None
        try:
            return CompletionToolCall.from_dict(raw_call)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _adjudicated_selection(
        cls,
        *,
        response: CompletionResponse,
        candidates: tuple[KnowledgeConversationCandidate, ...],
        max_answers: int,
    ) -> KnowledgeConversationSelection:
        tool_call = cls._normalized_tool_call(response)
        if tool_call is None or tool_call.name != _ADJUDICATION_TOOL_NAME:
            return cls._selection(
                decision_type=KnowledgeConversationDecisionType.UNAVAILABLE,
                llm_adjudication_used=True,
                reason_code="completion_malformed_output",
            )
        arguments = tool_call.arguments
        if set(arguments) != {"decision", "candidate_ids"}:
            return cls._selection(
                decision_type=KnowledgeConversationDecisionType.UNAVAILABLE,
                llm_adjudication_used=True,
                reason_code="completion_malformed_output",
            )
        decision = arguments.get("decision")
        raw_ids = arguments.get("candidate_ids")
        if decision not in {"answer", "clarify", "decline"} or not isinstance(
            raw_ids, list
        ):
            return cls._selection(
                decision_type=KnowledgeConversationDecisionType.UNAVAILABLE,
                llm_adjudication_used=True,
                reason_code="completion_malformed_output",
            )
        if decision != "answer":
            if raw_ids:
                return cls._selection(
                    decision_type=KnowledgeConversationDecisionType.UNAVAILABLE,
                    llm_adjudication_used=True,
                    reason_code="completion_invalid_candidate_ids",
                )
            decision_type = (
                KnowledgeConversationDecisionType.CLARIFY
                if decision == "clarify"
                else KnowledgeConversationDecisionType.DECLINE
            )
            return cls._selection(
                decision_type=decision_type,
                llm_adjudication_used=True,
                reason_code=f"llm_{decision}",
            )
        if not raw_ids or len(raw_ids) > max_answers:
            return cls._selection(
                decision_type=KnowledgeConversationDecisionType.UNAVAILABLE,
                llm_adjudication_used=True,
                reason_code="completion_invalid_candidate_ids",
            )
        parsed_ids: list[uuid.UUID] = []
        try:
            for raw_id in raw_ids:
                if not isinstance(raw_id, str):
                    raise ValueError
                parsed_ids.append(uuid.UUID(raw_id))
        except (TypeError, ValueError, AttributeError):
            return cls._selection(
                decision_type=KnowledgeConversationDecisionType.UNAVAILABLE,
                llm_adjudication_used=True,
                reason_code="completion_invalid_candidate_ids",
            )
        if len(set(parsed_ids)) != len(parsed_ids):
            return cls._selection(
                decision_type=KnowledgeConversationDecisionType.UNAVAILABLE,
                llm_adjudication_used=True,
                reason_code="completion_invalid_candidate_ids",
            )
        selected_ids = set(parsed_ids)
        candidate_ids = {candidate.candidate_id for candidate in candidates}
        if not selected_ids.issubset(candidate_ids):
            return cls._selection(
                decision_type=KnowledgeConversationDecisionType.UNAVAILABLE,
                llm_adjudication_used=True,
                reason_code="completion_invalid_candidate_ids",
            )
        selected = tuple(
            candidate
            for candidate in candidates
            if candidate.candidate_id in selected_ids
        )
        return cls._selection(
            decision_type=KnowledgeConversationDecisionType.ANSWER,
            selected=selected,
            llm_adjudication_used=True,
            reason_code="llm_selected_candidates",
        )

    async def select(
        self,
        *,
        query_text: str,
        candidates: tuple[KnowledgeConversationCandidate, ...],
        policy: KnowledgeConversationSelectionPolicy,
    ) -> KnowledgeConversationSelection:
        """Select deterministic winners or safely adjudicate an ambiguous set."""
        if not isinstance(query_text, str):
            raise TypeError("query_text must be a string.")
        normalized_query = query_text.strip()
        if normalized_query == "":
            raise ValueError("query_text must be non-empty.")
        if not isinstance(policy, KnowledgeConversationSelectionPolicy):
            raise TypeError("policy must be a KnowledgeConversationSelectionPolicy.")
        self._validate_candidates(candidates)
        ranked = self._ranked_candidates(candidates, policy)
        deterministic = self._deterministic_winners(ranked, policy)
        if deterministic:
            return self._selection(
                decision_type=KnowledgeConversationDecisionType.ANSWER,
                selected=deterministic,
                llm_adjudication_used=False,
                reason_code="deterministic_similarity_winner",
            )
        adjudication_candidates = self._eligible_candidates(
            ranked,
            policy.adjudication_min_similarity,
        )
        if not adjudication_candidates:
            return self._selection(
                decision_type=KnowledgeConversationDecisionType.DECLINE,
                llm_adjudication_used=False,
                reason_code="no_acceptable_candidate",
            )
        if not policy.llm_adjudication_enabled:
            return self._selection(
                decision_type=KnowledgeConversationDecisionType.CLARIFY,
                llm_adjudication_used=False,
                reason_code="llm_adjudication_disabled",
            )
        if self._completion_gateway is None:
            return self._selection(
                decision_type=KnowledgeConversationDecisionType.UNAVAILABLE,
                llm_adjudication_used=False,
                reason_code="completion_gateway_unavailable",
            )
        request = self._completion_request(
            query_text=normalized_query,
            candidates=adjudication_candidates,
            max_answers=policy.max_answers,
        )
        try:
            response = await self._completion_gateway.get_completion(request)
        except Exception:  # pylint: disable=broad-exception-caught
            return self._selection(
                decision_type=KnowledgeConversationDecisionType.UNAVAILABLE,
                llm_adjudication_used=True,
                reason_code="completion_gateway_error",
            )
        return self._adjudicated_selection(
            response=response,
            candidates=adjudication_candidates,
            max_answers=policy.max_answers,
        )

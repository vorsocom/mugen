# Knowledge Conversation Selection

Core owns a provider-neutral selection boundary for applications that render
approved Knowledge Pack answers in customer conversations. The boundary accepts
only `ApprovedKnowledgeResult` values returned by relationally rehydrated
Knowledge Pack retrieval; callers do not construct completion-provider requests.

## Public contract

Import the stable types from:

```python
from mugen.core.plugin.knowledge_pack.contract.service import (
    KnowledgeConversationCandidate,
    KnowledgeConversationDecisionType,
    KnowledgeConversationSelectionPolicy,
    IKnowledgeConversationSelector,
)
```

Resolve the runtime implementation through the Core extension-service key:

```python
from mugen.core import di

selector: IKnowledgeConversationSelector = (
    di.container.get_required_ext_service(
        di.EXT_SERVICE_KNOWLEDGE_CONVERSATION_SELECTOR
    )
)
```

The service is registered whenever the Knowledge Pack framework extension is
active. A completion gateway is optional.

## Selection policy

`KnowledgeConversationSelectionPolicy` requires:

- `auto_answer_min_similarity`: minimum similarity for deterministic answers;
- `adjudication_min_similarity`: lower bound for the ambiguous candidate set;
- `winner_margin`: required separation at the selected/unselected cutoff;
- `candidate_limit`: maximum candidates considered by the selector;
- `max_answers`: one to three answers;
- `llm_adjudication_enabled`: whether ambiguous candidates may use completion.

Candidates are ranked by similarity with candidate ID as the stable tie-breaker.
All candidates at or above the auto-answer threshold may be selected up to
`max_answers`. The lowest selected candidate must beat the best remaining
adjudication candidate by `winner_margin`. This deterministic path does not call
completion and remains available when completion is disabled or unavailable.

If no deterministic set exists:

- candidates below the adjudication floor produce `decline`;
- disabled adjudication produces `clarify`;
- absent, failed, or malformed completion produces `unavailable`;
- valid adjudication may produce `answer`, `clarify`, or `decline`.

## Completion safety boundary

Completion receives a provider-neutral `CompletionRequest` with one strict tool.
The tool can only return a decision and supplied candidate UUIDs. Core ignores
completion response prose and rejects:

- missing, multiple, or incorrectly named tool calls;
- malformed arguments or extra fields;
- unknown, duplicate, or non-UUID candidate IDs;
- selections larger than `max_answers`;
- IDs outside the policy-limited adjudication candidate set.

No generated prose appears in `KnowledgeConversationSelection`. Answer decisions
contain selected candidate IDs and immutable pack, version, entry, revision,
scope, tenant, and Service Profile provenance. Downstream renderers must map the
selected IDs back to the supplied candidates and render only their approved
relational content.

## Decision ledger fields

Every decision records:

- normalized decision type;
- selected candidate IDs and relational provenance when applicable;
- whether semantic retrieval was used;
- whether completion adjudication was used;
- a stable machine-readable reason code.

Invalid caller input raises a contract error before selection. Runtime
adjudication failures are returned as explicit fail-closed decisions.

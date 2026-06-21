# Working with muGen Gateways

Status: Draft  
Last Updated: 2026-06-21
Audience: Core and downstream plugin teams

## Purpose

This document explains gateway contracts and currently supported completion,
knowledge, email, and SMS gateway implementations in muGen.

Runtime configuration uses strict provider tokens (for example `anthropic`, `bedrock`,
`cerebras`, `groq`, `openai`, `azure_foundry`, `sambanova`, `vertex`,
`chromadb`, `milvus`, `pinecone`, `pgvector`, `qdrant`, `weaviate`, `smtp`,
`ses`, `twilio`), not
Python module paths.

For ECS/container overlay examples and selected-provider credential validation,
see [Container deployment and runtime overlays](container-deployment.md).

## Completion Gateway Contract

Completion gateways implement:

- `ICompletionGateway.get_completion(request)`

Request and response payloads are normalized by
`mugen/core/contract/gateway/completion.py`:

- `CompletionMessage(role, content)`
  - `content` supports string, object, list-of-objects, or null.
- `CompletionInferenceConfig(max_completion_tokens, temperature, top_p, stop, stream, stream_options)`
  - `max_completion_tokens` is the canonical token-limit field.
- `CompletionReasoningConfig(mode, effort, budget_tokens, include_encrypted_state, visibility)`
- `CompletionTool(name, description, input_schema, strict, kind, provider_hints)`
- `CompletionToolCall(id, name, arguments, provider_item)`
- `CompletionToolResult(tool_call_id, name, content, is_error)`
- `CompletionContinuationState(provider, response_id, conversation_id, output_items, reasoning_items, thinking_blocks, redacted_thinking_blocks, provider_state)`
- `CompletionRequest(messages, operation, model, inference, reasoning, tools, tool_results, continuation_state, vendor_params)`
- `CompletionResponse(content, model, stop_reason, message, tool_calls, output_items, reasoning_state, provider_state, usage, vendor_fields, raw)`
  - `content` may be structured (not string-only).
  - `message` and `tool_calls` preserve richer assistant outputs.
- `reasoning_state` and `provider_state` are opaque provider continuation data.
- `CompletionUsage(input_tokens, output_tokens, total_tokens, reasoning_tokens, vendor_fields)`
  - `vendor_fields` carries provider-specific usage/timing metadata.
- `CompletionGatewayError(provider, operation, message, cause)`

Reasoning-workflow fields are additive and backward-compatible with existing
chat-shaped requests. Provider adapters that do not understand normalized
reasoning, tools, tool results, or continuation state must either ignore absent
fields or raise a deterministic `CompletionGatewayError` when a request asks for
unsupported workflow features.

Do not emit raw reasoning items, encrypted reasoning, `thinking` blocks,
`redacted_thinking` blocks, or provider credentials to user-visible responses or
normal logs. Log-safe serializers summarize counts and provider state keys
instead.

Operation configs may define provider-neutral reasoning defaults for adapters
that support them:

- `[<provider>] api.<operation>.reasoning.mode`
  - expected values are provider-specific, but normalized adapters should use
    `adaptive`, `enabled`, or `disabled` where possible.
- `[<provider>] api.<operation>.reasoning.effort`
- `[<provider>] api.<operation>.reasoning.budget_tokens`
- `[<provider>] api.<operation>.reasoning.include_encrypted_state`
- `[<provider>] api.<operation>.reasoning.visibility`
  - default behavior is `opaque`; raw provider reasoning remains replay state,
    not display content.

Reasoning defaults are per operation, so `api.classification.reasoning.*` and
`api.completion.reasoning.*` can differ. Keep `visibility = "opaque"` unless a
provider adapter explicitly documents another safe display mode.

Operation configs can suppress sampling controls for models that reject them:

- `[<provider>] api.<operation>.sampling_controls = "enabled" | "disabled"`
- `enabled` preserves provider-specific behavior for configured or request-level
  `temperature` and `top_p`.
- `disabled` omits `temperature` and `top_p` from operation defaults and
  `CompletionInferenceConfig`. OpenAI-compatible Responses requests also ignore
  OpenAI vendor params named `temperature` and `top_p` while disabled.
- JSON overlays are deep-merged with the sample config. When inherited
  `temp`/`top_p` defaults must not be sent, set
  `api.<operation>.sampling_controls = "disabled"` instead of omitting those
  keys in the overlay.

## Email Gateway Contract

Outbound email gateways implement:

- `IEmailGateway.send_email(request)`

Request and response payloads are normalized by
`mugen/core/contract/gateway/email.py`:

- `EmailAttachment(path, content_bytes, filename, mime_type)`
  - Exactly one source must be set: `path` xor `content_bytes`.
  - `filename` is required for in-memory content.
- `EmailSendRequest(to, cc, bcc, subject, text_body, html_body, from_address, reply_to, headers, attachments)`
  - At least one recipient in `to`/`cc`/`bcc`.
  - At least one body variant in `text_body` or `html_body`.
  - Optional strings are normalized and defaults are materialized.
- `EmailSendResult(message_id, accepted_recipients, rejected_recipients)`
- `EmailGatewayError(provider, operation, message, cause)`

## SMS Gateway Contract

Outbound SMS gateways implement:

- `ISMSGateway.send_sms(request)`

Request and response payloads are normalized by
`mugen/core/contract/gateway/sms.py`:

- `SMSSendRequest(to, body, from_number)`
  - `to` and `body` are required non-empty strings.
  - `from_number` is optional and normalized when provided.
- `SMSSendResult(message_id, recipient, provider_status)`
- `SMSGatewayError(provider, operation, message, cause)`

## Knowledge Gateway Contract

Knowledge gateways implement:

- `IKnowledgeGateway.check_readiness()`
- `IKnowledgeGateway.search(params)`
- `IKnowledgeGateway.aclose()`

Request and response payloads are normalized by
`mugen/core/contract/gateway/knowledge.py`:

- `KnowledgeSearchResult(items, total_count, raw_vendor)`
- `KnowledgeGatewayRuntimeError(provider, operation, cause)`

Provider-specific search params are carried by vendor DTO types under
`mugen/core/contract/dto/*`.

## Completion Provider Gateways

### Anthropic

Module: `mugen.core.gateway.completion.anthropic`

Provider token: `anthropic`

The direct Anthropic gateway uses the Messages API through `aiohttp`; no
Anthropic SDK dependency is required. The non-stream path is implemented first.
Requests with `CompletionInferenceConfig.stream=true` or
`vendor_params["stream"]=true` fail with a deterministic
`CompletionGatewayError`.

The gateway maps normalized reasoning and tool workflow fields to Claude
Messages:

- `CompletionTool` serializes to `{name, description, input_schema}`.
- `CompletionToolResult` serializes to `tool_result` user content blocks.
- `CompletionReasoningConfig(mode="adaptive")` serializes to
  `thinking: {type: "adaptive"}` and `output_config.effort` when effort is set.
- `CompletionReasoningConfig(mode="enabled", budget_tokens=N)` serializes to
  manual extended thinking.
- `CompletionReasoningConfig(mode="disabled")` omits `thinking`, except known
  always-on Claude reasoning models fail fast.
- `visibility="opaque"` maps to `thinking.display="omitted"` so thinking
  signatures remain replayable without surfacing readable thinking text.

Responses expose only final text in `CompletionResponse.content`; `thinking`
and `redacted_thinking` blocks are stored under
`CompletionResponse.reasoning_state` as opaque replay state. Tool-use blocks
are normalized to `CompletionToolCall`.

Current Claude capability checks reject known unsupported combinations:

- Fable 5, Mythos 5, and Mythos Preview reject disabled thinking.
- Fable 5, Mythos 5, Opus 4.8, and Opus 4.7 reject manual
  `mode="enabled"` thinking.
- Adaptive thinking is accepted only for known adaptive-capable model families.

Direct Anthropic adaptive-thinking example:

```toml
[anthropic]
api.completion.model = "<claude-model-with-adaptive-thinking>"
api.completion.max_completion_tokens = 4096
api.completion.sampling_controls = "disabled"
api.completion.reasoning.mode = "adaptive"
api.completion.reasoning.effort = "medium"
api.completion.reasoning.visibility = "opaque"
```

### AWS Bedrock

Module: `mugen.core.gateway.completion.bedrock`

Runtime mode is controlled per request by
`CompletionRequest.vendor_params["bedrock_api"]`:

- `auto` (default): call `Converse`; fallback to `InvokeModel` when Bedrock
  reports the model does not support `Converse`.
- `converse`: always use `Converse`.
- `invoke_model`: always use `InvokeModel`.

For Bedrock-hosted Claude models (`anthropic.*` and regional `*.anthropic.*`
model IDs), normalized reasoning/tools/tool-results/continuation state or
operation-level reasoning defaults automatically use Claude-native
`InvokeModel` serialization in `auto` mode. Explicit `bedrock_api="converse"`
with those normalized workflow fields fails fast until Bedrock Converse content
block mapping is implemented.

In all modes, the default model and inference values come from
`[aws.bedrock] api.<operation>.*` in `mugen.toml` when not overridden in
`CompletionRequest`.

#### Bedrock Readiness Behavior

- Validates both `classification` and `completion` operation configs.
- Executes a bounded `invoke_model` probe at startup.
- Treats expected Bedrock validation probe errors as reachable/authenticated.
- Fails readiness on auth/network/provider failures.

#### Built-in `InvokeModel` Family Support

When fallback or explicit `invoke_model` mode is used, muGen can serialize
multiple provider-specific bodies through a common request contract.

Model ID prefixes mapped by default:

- `anthropic.*`
- regional `*.anthropic.*`
- `meta.*`
- `amazon.titan-text*`
- `amazon.nova*`
- `ai21.j2*`
- `ai21.jamba*`
- `cohere.command-r*`
- `cohere.*`
- `mistral.*` (chat serializer for model IDs containing `mistral-large`,
  `pixtral-large`, or `ministral`; otherwise prompt serializer)
- `deepseek.*`
- `openai.*`
- `writer.*`

If no known family is detected, provide either:

- `vendor_params["invoke_body"]` for a full body override, or
- `vendor_params["invoke_family"]` to force a known family serializer.

#### Bedrock Vendor Parameters

Supported Bedrock-specific keys in `CompletionRequest.vendor_params`:

- General mode selection:
  - `bedrock_api`: `auto | converse | invoke_model`
- Converse request options:
  - `additional_model_request_fields`
  - `tool_config`
  - `guardrail_config`
  - `prompt_variables`
  - `additional_model_response_field_paths`
- Invoke request options:
  - `invoke_family`
  - `invoke_body`
  - `invoke_extra_fields`
  - `accept`
  - `content_type`
  - `top_k` (Nova helper)
  - `anthropic_version`
- Invoke response parsing overrides:
  - `invoke_response_paths`
  - `invoke_stop_reason_paths`

For Claude `InvokeModel`, normalized tools and tool results use Anthropic
Messages content blocks, adaptive reasoning effort is placed under
`output_config`, and `thinking`/`redacted_thinking` blocks are preserved exactly
in `CompletionContinuationState`.

Bedrock-hosted Claude adaptive-thinking example:

```toml
[aws.bedrock]
api.region = "us-east-1"
api.completion.model = "<anthropic-claude-model-id>"
api.completion.max_completion_tokens = 4096
api.completion.sampling_controls = "disabled"
api.completion.reasoning.mode = "adaptive"
api.completion.reasoning.effort = "medium"
api.completion.reasoning.visibility = "opaque"
```

### Groq

Module: `mugen.core.gateway.completion.groqq`

Supports normalized inference fields:

- `max_completion_tokens`
- `temperature`
- `top_p`
- `stop`
- `stream`
- `stream_options`

Groq-specific optional keys are forwarded from
`CompletionRequest.vendor_params`:

- `citation_options`
- `compound_custom`
- `disable_tool_validation`
- `documents`
- `exclude_domains`
- `frequency_penalty`
- `function_call`
- `functions`
- `include_domains`
- `include_reasoning`
- `logit_bias`
- `logprobs`
- `metadata`
- `n`
- `parallel_tool_calls`
- `presence_penalty`
- `reasoning_effort`
- `reasoning_format`
- `response_format`
- `search_settings`
- `seed`
- `service_tier`
- `store`
- `tool_choice`
- `tools`
- `top_logprobs`
- `user`
- `verbosity`

#### Groq Readiness Behavior

- Validates both `classification` and `completion` operation configs.
- Executes a bounded `models.list` probe at startup.
- Fails readiness on missing probe hooks, timeouts, or provider/network errors.

### OpenAI

Module: `mugen.core.gateway.completion.openai`

OpenAI surface routing:

- Operation default:
  - `[openai] api.<operation>.surface = "chat_completions" | "responses"`
- Per-request override:
  - `CompletionRequest.vendor_params["openai_api"]`
  - allowed values: `chat_completions`, `responses`
- Requests with normalized `reasoning`, `tools`, `tool_results`, or
  `continuation_state` automatically use Responses unless the request explicitly
  sets `openai_api = "chat_completions"`.
- Explicit Chat Completions requests that include normalized reasoning workflow
  fields fail fast with `CompletionGatewayError`.

Supports normalized inference fields:

- `max_completion_tokens`
- `temperature`
- `top_p`
- `stop` (chat mode only)
- `stream`
- `stream_options`

Chat Completions passthrough keys from `CompletionRequest.vendor_params`:

- `audio`
- `frequency_penalty`
- `function_call`
- `functions`
- `logit_bias`
- `logprobs`
- `metadata`
- `modalities`
- `n`
- `parallel_tool_calls`
- `presence_penalty`
- `reasoning_effort`
- `response_format`
- `seed`
- `service_tier`
- `store`
- `tool_choice`
- `tools`
- `top_logprobs`
- `user`

Responses passthrough keys from `CompletionRequest.vendor_params`:

- `include`
- `max_tool_calls`
- `previous_response_id`
- `prompt`
- `prompt_cache_key`
- `reasoning`
- `safety_identifier`
- `text`
- `truncation`
- `conversation`
- `metadata`
- `parallel_tool_calls`
- `service_tier`
- `store`
- `temperature`
- `top_p`
- `tool_choice`
- `tools`
- `top_logprobs`
- `user`

OpenAI compatibility notes:

- muGen targets OpenAI public API semantics (`api.openai.com`) for:
  - Chat Completions
  - Responses
- Default surface remains `chat_completions`.
- In Responses mode, system-role messages are joined into `instructions`; other
  messages are sent as `input`.
- In Responses mode, token limit is sent as `max_output_tokens`.
- In Responses mode, normalized `CompletionTool` values are serialized as flat
  function tools (`type`, `name`, `description`, `parameters`, `strict`).
- In Responses mode, normalized `CompletionToolResult` values are serialized as
  `function_call_output` input items.
- OpenAI continuation uses `previous_response_id` when available. Without a
  response id, preserved reasoning/output items are replayed before new input
  for stateless continuation.
- `CompletionReasoningConfig.effort` maps to OpenAI `reasoning.effort`.
  `include_encrypted_state = true` adds
  `reasoning.encrypted_content` to `include`.
- Responses output items are copied to `CompletionResponse.output_items`;
  reasoning items and non-reasoning output items are retained in opaque
  `CompletionContinuationState` for replay.
- In Chat Completions mode, token limit defaults to `max_completion_tokens`.
- Responses-mode validation/API failures are fail-fast; there is no implicit
  fallback to Chat Completions.
- API key resolution is config-only (`[openai] api.key`).
- Optional endpoint and timeout settings are supported via
  `[openai] api.base_url` and `[openai] api.timeout_seconds`.
- Non-stream and stream responses preserve tool calls, usage metadata, and
  structured output blocks in normalized response fields.

OpenAI Responses example for a model that rejects sampling controls:

```toml
[openai]
api.completion.model = "gpt-5.5"
api.completion.surface = "responses"
api.completion.sampling_controls = "disabled"
api.completion.max_completion_tokens = 4046
api.completion.reasoning.effort = "medium"
api.completion.reasoning.include_encrypted_state = true
api.completion.reasoning.visibility = "opaque"
```

#### OpenAI Readiness Behavior

- Validates both `classification` and `completion` operation configs.
- Executes a bounded `models.list` probe at startup.
- Supports SDK signature differences (`list(limit=1)` fallback to `list()`).
- Fails readiness on missing probe hooks, timeouts, or provider/network errors.

### Cerebras

Module: `mugen.core.gateway.completion.cerebras`

Cerebras surface routing:

- Operation default:
  - `[cerebras] api.<operation>.surface = "chat_completions"`
- Per-request override:
  - `CompletionRequest.vendor_params["cerebras_api"]`
  - allowed value: `chat_completions`

Compatibility notes:

- Only chat completions are supported in this gateway.
- `CompletionRequest.vendor_params["openai_api"]` is rejected.
- Optional endpoint and timeout settings are supported via
  `[cerebras] api.base_url` and `[cerebras] api.timeout_seconds`.
- If `api.base_url` is empty, the gateway defaults to `https://api.cerebras.ai/v1`.
- Non-stream and stream responses preserve tool calls and usage metadata in
  normalized response fields.

Supports normalized inference fields:

- `max_completion_tokens`
- `temperature`
- `top_p`
- `stop`
- `stream`

Cerebras-specific optional keys are forwarded from
`CompletionRequest.vendor_params`:

- `clear_thinking`
- `logprobs`
- `n`
- `parallel_tool_calls`
- `prediction`
- `reasoning_effort`
- `response_format`
- `seed`
- `service_tier`
- `tool_choice`
- `tools`
- `top_logprobs`
- `user`

#### Cerebras Readiness Behavior

- Validates both `classification` and `completion` operation configs.
- Executes a bounded `models.list` probe at startup.
- Supports SDK signature differences (`list(limit=1)` fallback to `list()`).
- Fails readiness on missing probe hooks, timeouts, or provider/network errors.

### Azure AI Foundry

Module: `mugen.core.gateway.completion.azure_foundry`

Azure AI Foundry surface routing:

- Operation default:
  - `[azure.foundry] api.<operation>.surface = "chat_completions" | "responses"`
- Per-request override:
  - `CompletionRequest.vendor_params["azure_foundry_api"]`
  - allowed values: `chat_completions`, `responses`
- Backward-compatible alias:
  - `CompletionRequest.vendor_params["openai_api"]` is accepted and mapped.

Supports the same normalized inference fields and vendor passthrough behavior as
the OpenAI gateway.

Azure AI Foundry compatibility notes:

- Uses OpenAI-compatible request/response payloads.
- API key and endpoint are config-only:
  - `[azure.foundry] api.key`
  - `[azure.foundry] api.base_url`
- Sends `api-key` header on every request.
- Optional API version query parameter can be configured via
  `[azure.foundry] api.version` and is sent as `api-version=<value>`.
- Optional timeout can be configured via `[azure.foundry] api.timeout_seconds`.

#### Azure AI Foundry Readiness Behavior

- Validates both `classification` and `completion` operation configs.
- Executes a bounded `models.list` probe at startup.
- Supports SDK signature differences (`list(limit=1)` fallback to `list()`).
- Fails readiness on missing probe hooks, timeouts, or provider/network errors.

### SambaNova

Module: `mugen.core.gateway.completion.sambanova`

Supports normalized inference fields:

- `max_completion_tokens`
- `temperature`
- `top_p`
- `stop`
- `stream`
- `stream_options`

SambaNova-specific optional keys are forwarded from
`CompletionRequest.vendor_params`:

- `chat_template_kwargs`
- `do_sample`
- `frequency_penalty`
- `logprobs`
- `n`
- `parallel_tool_calls`
- `presence_penalty`
- `reasoning_effort`
- `response_format`
- `seed`
- `tool_choice`
- `tools`
- `top_k`
- `top_logprobs`
- `user`

SambaNova compatibility notes:

- Authorization uses `Bearer` token.
- Token limit is serialized from `max_completion_tokens`.
- Streaming uses contract fields (`inference.stream`, `inference.stream_options`).

#### SambaNova Readiness Behavior

- Validates both `classification` and `completion` operation configs.
- Executes a bounded HTTP probe against the configured completion endpoint.
- Treats explicit validation-style probe responses (`400`/`422`) as reachable.
- Fails readiness on auth errors (`401`/`403`), provider errors (`5xx`), or
  transport failures.

### Vertex

Module: `mugen.core.gateway.completion.vertex`

Uses Vertex Gemini native `generateContent` (non-stream in current implementation).

Supports normalized inference fields:

- `max_completion_tokens`
- `temperature`
- `top_p`
- `stop`

Per-request stream behavior:

- `inference.stream=true` is rejected with a deterministic `CompletionGatewayError`
  because streaming is not yet implemented for the Vertex gateway.

Vertex-specific optional keys are forwarded from
`CompletionRequest.vendor_params`:

- `safety_settings` -> `safetySettings`
- `tools` -> `tools`
- `tool_config` -> `toolConfig`
- `cached_content` -> `cachedContent`
- `response_mime_type` -> `generationConfig.responseMimeType`
- `response_schema` -> `generationConfig.responseSchema`
- `candidate_count` -> `generationConfig.candidateCount`

Message serialization notes:

- `system` messages are joined into `systemInstruction`.
- `user` messages map to Vertex `contents[*].role=user`.
- `assistant` messages map to Vertex `contents[*].role=model`.
- Non-standard roles are coerced to `user` text with a role prefix.
- Structured content (`dict`/`list`) is serialized to JSON text for MVP.

Authentication and endpoint behavior:

- Auth precedence:
  - `[gcp.vertex] api.access_token` when configured.
  - otherwise ADC (`google.auth.default` + token refresh).
- The gateway targets:
  - `projects/{project}/locations/{location}/publishers/google/models/{model}:generateContent`
  - and supports fully qualified `projects/...` model paths when supplied.

#### Vertex Readiness Behavior

- Validates both `classification` and `completion` operation configs.
- Executes a bounded HTTP probe using the configured model.
- Treats explicit validation-style probe responses (`400`/`422`) as reachable.
- Fails readiness on auth errors (`401`/`403`), provider errors (`5xx`), or
  transport failures.

## Email Provider Gateways

### SMTP

Module: `mugen.core.gateway.email.smtp`

Behavior:

- Outbound-only sending (`send_email`) using blocking SMTP I/O wrapped in
  `asyncio.to_thread(...)`.
- Supports text-only, html-only, and multipart text+html MIME bodies.
- Supports attachments from local file paths and in-memory bytes.
- Sender policy:
  - request-level `from_address` overrides config.
  - fallback is `[smtp].default_from`.
- TLS/auth controls:
  - `use_ssl` for implicit TLS.
  - `starttls` / `starttls_required` for explicit TLS upgrade.
  - optional `username`/`password` login when both are configured.
- Transport/config/attachment failures raise `EmailGatewayError`.

## Knowledge Provider Gateways

Knowledge provider gateways are search adapters for downstream projections.
They are not the `knowledge_pack` governance source of truth.

Current generic gateway search contracts enforce tenant filtering and optional
`channel`, `locale`, and `category` filters. They do not expose first-class
`service_route_key` or `client_profile_key` request fields. Route/profile
isolation for production `knowledge_pack` evidence must be enforced before
ranking through `KnowledgeScopeService.list_published_revisions(...)`, through
`KnowledgePackContributor`, or through a downstream-owned projection contract
that explicitly adds and tests those fields.

### ChromaDB

Module: `mugen.core.gateway.knowledge.chromadb`

Behavior:

- Uses local sentence-transformer embeddings for semantic query vectors.
- Uses ChromaDB HTTP collection queries with a mandatory `tenant_id` metadata
  filter and optional scope filters (`channel`, `locale`, `category`).
- Requires strict metadata projection keys per result row:
  `tenant_id`, `knowledge_entry_revision_id`, `knowledge_pack_version_id`,
  `channel`, `locale`, `category`, `title`, `body`.
- Returns normalized items with revision/version IDs, scope values, title,
  snippet, similarity, and distance.
- Applies retry/timeout controls from `[chromadb] api.*`.
- Wraps provider transport/runtime failures as `KnowledgeGatewayRuntimeError`.

Readiness requirements:

- `chromadb.api.host` is configured
- `chromadb.search.collection` is configured
- configured Chroma collection is reachable
- local sentence-transformer encoder initializes successfully

### Qdrant

Module: `mugen.core.gateway.knowledge.qdrant`

Behavior:

- Uses local sentence-transformer embeddings for semantic query vectors.
- Queries a configured Qdrant collection using tenant-scoped and optional scope
  filters (`channel`, `locale`, `category`).
- Requires strict payload keys per point:
  `tenant_id`, `knowledge_entry_revision_id`, `knowledge_pack_version_id`,
  `channel`, `locale`, `category`, `title`, `body`.
- Returns normalized items with revision/version IDs, scope values, title,
  snippet, similarity, and distance.
- Applies retry/timeout controls from `[qdrant] api.*`.
- Wraps provider transport/runtime failures as `KnowledgeGatewayRuntimeError`.

Readiness requirements:

- `qdrant.api.url` is configured
- `qdrant.search.collection` exists and is reachable
- local sentence-transformer encoder initializes successfully

Migration note:

- Legacy Qdrant request fields (`collection_name`, `count`, `strategy`,
  `dataset`, `date_from`, `date_to`, `keywords`, `limit`) were removed in favor
  of the shared tenant-scoped semantic-search contract.

### Milvus

Module: `mugen.core.gateway.knowledge.milvus`

Behavior:

- Uses local sentence-transformer embeddings for semantic query vectors.
- Queries a configured Milvus collection using tenant-scoped and optional scope
  filters (`channel`, `locale`, `category`).
- Requires strict payload projection keys per hit:
  `tenant_id`, `knowledge_entry_revision_id`, `knowledge_pack_version_id`,
  `channel`, `locale`, `category`, `title`, `body`.
- Returns normalized items with revision/version IDs, scope values, title,
  snippet, similarity, and distance.
- Applies retry/timeout controls from `[milvus] api.*`.
- Wraps provider transport/runtime failures as `KnowledgeGatewayRuntimeError`.

Readiness requirements:

- `milvus.api.uri` is configured
- `milvus.search.collection` exists and is reachable
- local sentence-transformer encoder initializes successfully

### Pinecone

Module: `mugen.core.gateway.knowledge.pinecone`

Behavior:

- Uses local sentence-transformer embeddings for semantic query vectors.
- Queries a configured Pinecone index host with required tenant metadata
  filtering and optional scope filters (`channel`, `locale`, `category`).
- Requires strict metadata keys per match:
  `tenant_id`, `knowledge_entry_revision_id`, `knowledge_pack_version_id`,
  `channel`, `locale`, `category`, `title`, `body`.
- Returns normalized items with revision/version IDs, scope values, title,
  snippet, similarity, and distance.
- Supports metric-aware score mapping configured by `pinecone.search.metric`:
  - `cosine`: `similarity = score`, `distance = 1 - score`
  - `dotproduct`: `similarity = score`, `distance = null`
  - `euclidean`: `similarity = score`, `distance = null`
- Applies retry/timeout controls from `[pinecone] api.*`.
- Wraps provider transport/runtime failures as `KnowledgeGatewayRuntimeError`.

Readiness requirements:

- `pinecone.api.key` is configured
- `pinecone.api.host` is configured
- bounded `describe_index_stats` probe succeeds
- local sentence-transformer encoder initializes successfully

### pgvector

Module: `mugen.core.gateway.knowledge.pgvector`

Behavior:

- Uses local sentence-transformer embeddings for semantic query vectors.
- Queries a configured Postgres projection table with pgvector cosine distance.
- Enforces tenant filter and optional scope filters (`channel`, `locale`,
  `category`).
- Returns normalized items with revision/version IDs, scope values, title,
  snippet, similarity, and distance.
- Applies retry/timeout controls from `[pgvector] api.*`.
- Wraps provider transport/runtime failures as `KnowledgeGatewayRuntimeError`.

Readiness requirements:

- DB connectivity (`SELECT 1`)
- `vector` extension installed
- configured projection table exists
- required columns exist (`tenant_id`, `knowledge_entry_revision_id`,
  `knowledge_pack_version_id`, `channel`, `locale`, `category`, `title`, `body`,
  `embedding`)
- `embedding` column type is `vector`
- at least one `ivfflat` or `hnsw` index on `embedding`

### Weaviate

Module: `mugen.core.gateway.knowledge.weaviate`

Behavior:

- Uses local sentence-transformer embeddings for semantic query vectors.
- Queries a configured Weaviate collection using tenant-scoped and optional
  scope filters (`channel`, `locale`, `category`).
- Requires strict object properties per result:
  `tenant_id`, `knowledge_entry_revision_id`, `knowledge_pack_version_id`,
  `channel`, `locale`, `category`, `title`, `body`.
- Returns normalized items with revision/version IDs, scope values, title,
  snippet, similarity, and distance.
- Applies retry/timeout controls from `[weaviate] api.*`.
- Wraps provider transport/runtime failures as `KnowledgeGatewayRuntimeError`.

Readiness requirements:

- `weaviate.api.http_host` is configured
- `weaviate.api.grpc_host` is configured
- bounded `client.is_ready()` probe succeeds
- configured collection exists
- local sentence-transformer encoder initializes successfully

### Amazon SES

Module: `mugen.core.gateway.email.ses`

Behavior:

- Outbound-only sending (`send_email`) via AWS SES `send_raw_email`, wrapped in
  `asyncio.to_thread(...)`.
- Uses MIME/raw email payloads, so the same contract body and attachment
  semantics apply as SMTP:
  - text-only, html-only, and multipart text+html
  - file-path and in-memory-byte attachments
- Sender policy:
  - request-level `from_address` overrides config.
  - fallback is `[aws.ses].default_from`.
- AWS auth/config:
  - region is required (`[aws.ses] api.region`)
  - static credentials are optional; when set, access key and secret key must
    be provided together
  - optional session token and endpoint URL are supported
- optional `configuration_set_name` is forwarded to SES.
- Transport/config/attachment failures raise `EmailGatewayError`.

## SMS Provider Gateways

### Twilio

Module: `mugen.core.gateway.sms.twilio`

Behavior:

- Outbound-only sending (`send_sms`) via Twilio Programmable Messaging REST API.
- Readiness probe calls `GET /2010-04-01/Accounts/{AccountSid}.json`.
- Sends messages with `POST /2010-04-01/Accounts/{AccountSid}/Messages.json`
  using form-encoded payloads.
- Sender policy:
  - request-level `from_number` overrides config.
  - fallback is `[twilio].messaging.default_from`.
  - fallback after that is `[twilio].messaging.messaging_service_sid`.
  - configured `default_from` and `messaging_service_sid` are mutually
    exclusive.
- Twilio auth/config:
  - `account_sid` is required.
  - exactly one auth mode is allowed:
    - `api.auth_token`, or
    - `api.api_key_sid` + `api.api_key_secret`.
- Transport/config/provider failures raise `SMSGatewayError`.

## Configuration Example

```toml
[mugen.modules.core]
gateway.completion = "bedrock"
# gateway.completion = "cerebras"
# gateway.completion = "azure_foundry"
# gateway.completion = "vertex"
# Optional knowledge gateway.
# gateway.knowledge = "chromadb"
# gateway.knowledge = "milvus"
# gateway.knowledge = "pinecone"
# gateway.knowledge = "pgvector"
# gateway.knowledge = "qdrant"
# gateway.knowledge = "weaviate"
# Optional outbound email gateway.
# gateway.email = "smtp"
# gateway.email = "ses"
# Optional outbound SMS gateway.
# gateway.sms = "twilio"

[aws.bedrock]
api.region = "us-east-1"
api.access_key_id = "<aws-access-key-id>"
api.secret_access_key = "<aws-secret-access-key>"
api.completion.model = "amazon.nova-lite-v1:0"
api.completion.max_tokens = 1024
api.completion.temp = 0.2
api.completion.top_p = 0.9
api.completion.sampling_controls = "enabled"

[twilio]
api.account_sid = "<twilio-account-sid>"
api.auth_token = "<twilio-auth-token>"
api.api_key_sid = ""
api.api_key_secret = ""
api.base_url = "https://api.twilio.com"
api.timeout_seconds = 10.0
messaging.default_from = "+15550000001"
messaging.messaging_service_sid = ""

[cerebras]
api.key = "<cerebras-api-key>"
api.base_url = "https://api.cerebras.ai/v1"
api.classification.model = "llama-4-scout-17b-16e-instruct"
api.classification.surface = "chat_completions"
api.classification.temp = 0.0
api.classification.top_p = 1.0
api.classification.sampling_controls = "enabled"
api.classification.max_completion_tokens = 256
api.completion.model = "llama-4-scout-17b-16e-instruct"
api.completion.surface = "chat_completions"
api.completion.temp = 0.2
api.completion.top_p = 0.9
api.completion.sampling_controls = "enabled"
api.completion.max_completion_tokens = 1024
api.timeout_seconds = 30.0

[azure.foundry]
api.key = "<azure-foundry-api-key>"
api.base_url = "https://example.services.ai.azure.com/models"
api.version = "2025-04-01-preview"
api.classification.model = "gpt-4.1-mini"
api.classification.surface = "chat_completions"
api.classification.temp = 0.0
api.classification.top_p = 1.0
api.classification.sampling_controls = "enabled"
api.classification.max_completion_tokens = 256
api.completion.model = "gpt-4.1-mini"
api.completion.surface = "chat_completions"
api.completion.temp = 0.2
api.completion.top_p = 0.9
api.completion.sampling_controls = "enabled"
api.completion.max_completion_tokens = 1024
api.timeout_seconds = 30.0

[gcp.vertex]
api.project = "my-gcp-project"
api.location = "us-central1"
api.access_token = ""
api.classification.model = "gemini-2.0-flash-001"
api.classification.temp = 0.0
api.classification.top_p = 1.0
api.classification.sampling_controls = "enabled"
api.classification.max_completion_tokens = 256
api.completion.model = "gemini-2.0-flash-001"
api.completion.temp = 0.2
api.completion.top_p = 0.9
api.completion.sampling_controls = "enabled"
api.completion.max_completion_tokens = 1024
api.connect_timeout_seconds = 10.0
api.read_timeout_seconds = 30.0

[smtp]
host = "smtp.example.com"
port = 587
username = "<smtp-username>"
password = "<smtp-password>"
default_from = "noreply@example.com"
timeout_seconds = 30.0
use_ssl = false
starttls = true
starttls_required = true

[aws.ses]
api.region = "us-east-1"
api.access_key_id = "<aws-access-key-id>"
api.secret_access_key = "<aws-secret-access-key>"
api.session_token = ""
api.endpoint_url = ""
default_from = "noreply@example.com"
configuration_set_name = ""

[chromadb]
api.host = "localhost"
api.port = 8000
api.ssl = false
api.headers = {}
api.tenant = ""
api.database = ""
api.timeout_seconds = 10.0
api.max_retries = 2
api.retry_backoff_seconds = 0.5
search.collection = "downstream_kp_search_doc"
search.default_top_k = 10
search.max_top_k = 50
search.snippet_max_chars = 240
encoder.model = "all-mpnet-base-v2"
encoder.max_concurrency = 4

[milvus]
api.uri = "http://localhost:19530"
api.token = ""
api.timeout_seconds = 10.0
api.max_retries = 2
api.retry_backoff_seconds = 0.5
search.collection = "downstream_kp_search_doc"
search.vector_field = "embedding"
search.default_top_k = 10
search.max_top_k = 50
search.snippet_max_chars = 240
encoder.model = "all-mpnet-base-v2"
encoder.max_concurrency = 4

[pinecone]
api.key = "<pinecone-api-key>"
api.host = "https://your-index-host.svc.pinecone.io"
api.timeout_seconds = 10.0
api.max_retries = 2
api.retry_backoff_seconds = 0.5
search.namespace = ""
search.metric = "cosine"
search.default_top_k = 10
search.max_top_k = 50
search.snippet_max_chars = 240
encoder.model = "all-mpnet-base-v2"
encoder.max_concurrency = 4

[qdrant]
api.key = "<qdrant-api-key>"
api.url = ""
api.timeout_seconds = 10.0
api.max_retries = 2
api.retry_backoff_seconds = 0.5
search.collection = "downstream_kp_search_doc"
search.default_top_k = 10
search.max_top_k = 50
search.snippet_max_chars = 240
encoder.model = "all-mpnet-base-v2"
encoder.max_concurrency = 4

[pgvector]
search.schema = "mugen"
search.table = "downstream_kp_search_doc"
search.metric = "cosine"
search.default_top_k = 10
search.max_top_k = 50
search.snippet_max_chars = 240
api.timeout_seconds = 10.0
api.max_retries = 2
api.retry_backoff_seconds = 0.5
encoder.model = "all-mpnet-base-v2"
encoder.max_concurrency = 4

[weaviate]
api.http_host = "localhost"
api.http_port = 8080
api.http_secure = false
api.grpc_host = "localhost"
api.grpc_port = 50051
api.grpc_secure = false
api.key = "<weaviate-api-key>"
api.headers = {}
api.timeout_seconds = 10.0
api.max_retries = 2
api.retry_backoff_seconds = 0.5
search.collection = "DownstreamKPSearchDoc"
search.target_vector = ""
search.default_top_k = 10
search.max_top_k = 50
search.snippet_max_chars = 240
encoder.model = "all-mpnet-base-v2"
encoder.max_concurrency = 4
```

# Working with muGen Gateways

Status: Draft  
Last Updated: 2026-02-21  
Audience: Core and downstream plugin teams

## Purpose

This document explains gateway contracts and currently supported completion
and email gateway implementations in muGen.

## Completion Gateway Contract

Completion gateways implement:

- `ICompletionGateway.get_completion(request, operation="completion")`

Request and response payloads are normalized by
`mugen/core/contract/gateway/completion.py`:

- `CompletionMessage(role, content)`
  - `content` supports string, object, list-of-objects, or null.
- `CompletionInferenceConfig(max_completion_tokens, max_tokens, temperature, top_p, stop, stream, stream_options)`
  - `max_completion_tokens` is preferred.
  - `max_tokens` is a compatibility alias.
  - `effective_max_tokens` applies precedence: `max_completion_tokens` then `max_tokens`.
- `CompletionRequest(messages, operation, model, inference, vendor_params)`
- `CompletionResponse(content, model, stop_reason, message, tool_calls, usage, vendor_fields, raw)`
  - `content` may be structured (not string-only).
  - `message` and `tool_calls` preserve richer assistant outputs.
- `CompletionUsage(input_tokens, output_tokens, total_tokens, vendor_fields)`
  - `vendor_fields` carries provider-specific usage/timing metadata.
- `CompletionGatewayError(provider, operation, message, cause)`

Legacy list-of-dicts context payloads are still accepted through
`normalise_completion_request(...)`.

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

## Completion Provider Gateways

### AWS Bedrock

Module: `mugen.core.gateway.completion.bedrock`

Runtime mode is controlled per request by
`CompletionRequest.vendor_params["bedrock_api"]`:

- `auto` (default): call `Converse`; fallback to `InvokeModel` when Bedrock
  reports the model does not support `Converse`.
- `converse`: always use `Converse`.
- `invoke_model`: always use `InvokeModel`.

In all modes, the default model and inference values come from
`[aws.bedrock] api.<operation>.*` in `mugen.toml` when not overridden in
`CompletionRequest`.

#### Built-in `InvokeModel` Family Support

When fallback or explicit `invoke_model` mode is used, muGen can serialize
multiple provider-specific bodies through a common request contract.

Model ID prefixes mapped by default:

- `anthropic.*`
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

### Groq

Module: `mugen.core.gateway.completion.groqq`

Supports normalized inference fields:

- `max_completion_tokens` (preferred token-limit field)
- `max_tokens` compatibility alias (used only when explicitly requested)
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

Groq compatibility notes:

- By default, muGen sends `max_completion_tokens`.
- To force deprecated `max_tokens` serialization for compatibility, set
  `vendor_params["use_legacy_max_tokens"] = true`.
- Non-stream and stream responses both preserve structured assistant payloads,
  tool calls, and usage metadata in normalized response fields.

### OpenAI

Module: `mugen.core.gateway.completion.openai`

OpenAI surface routing:

- Operation default:
  - `[openai] api.<operation>.surface = "chat_completions" | "responses"`
- Per-request override:
  - `CompletionRequest.vendor_params["openai_api"]`
  - allowed values: `chat_completions`, `responses`

Supports normalized inference fields:

- `max_completion_tokens` (preferred request field)
- `max_tokens` compatibility alias
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
- In Chat Completions mode, token limit defaults to `max_completion_tokens`.
- To force deprecated `max_tokens` serialization for compatibility, set
  `vendor_params["use_legacy_max_tokens"] = true` (chat mode only).
- Responses-mode validation/API failures are fail-fast; there is no implicit
  fallback to Chat Completions.
- API key resolution is config-only (`[openai] api.key`).
- Optional endpoint and timeout settings are supported via
  `[openai] api.base_url` and `[openai] api.timeout_seconds`.
- Non-stream and stream responses preserve tool calls, usage metadata, and
  structured output blocks in normalized response fields.

### SambaNova

Module: `mugen.core.gateway.completion.sambanova`

Supports normalized inference fields:

- `max_completion_tokens` / `max_tokens` via `effective_max_tokens`
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

- Authorization defaults to `Bearer` token.
- For legacy environments that still require `Basic`, set
  `vendor_params["sambanova_auth_scheme"] = "basic"` (or set
  `auth_scheme = "basic"` in operation config).
- Token-limit field defaults to `max_tokens`.
- To emit `max_completion_tokens`, set
  `vendor_params["sambanova_token_limit_field"] = "max_completion_tokens"`.
- To emit both fields in the same request, set
  `vendor_params["sambanova_emit_legacy_max_tokens"] = true`.
- Streaming uses contract fields first (`inference.stream`,
  `inference.stream_options`) and keeps legacy `vendor_params["stream"]` and
  `vendor_params["include_usage"]` as compatibility fallbacks.

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

## Configuration Example

```toml
[mugen.modules.core]
gateway.completion = "mugen.core.gateway.completion.bedrock"
# Optional outbound email gateway.
# gateway.email = "mugen.core.gateway.email.smtp"

[aws.bedrock]
api.region = "us-east-1"
api.access_key_id = "<aws-access-key-id>"
api.secret_access_key = "<aws-secret-access-key>"
api.completion.model = "amazon.nova-lite-v1:0"
api.completion.max_tokens = 1024
api.completion.temp = 0.2
api.completion.top_p = 0.9

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
```

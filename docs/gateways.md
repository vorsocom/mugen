# Working with muGen Gateways

Status: Draft  
Last Updated: 2026-02-16  
Audience: Core and downstream plugin teams

## Purpose

This document explains the gateway contract and the currently supported
completion gateway implementations in muGen.

## Completion Gateway Contract

Completion gateways implement:

- `ICompletionGateway.get_completion(request, operation="completion")`

Request and response payloads are normalized by
`mugen/core/contract/gateway/completion.py`:

- `CompletionMessage(role, content)`
- `CompletionInferenceConfig(max_tokens, temperature, top_p, stop)`
- `CompletionRequest(messages, operation, model, inference, vendor_params)`
- `CompletionResponse(content, model, stop_reason, usage, vendor_fields, raw)`
- `CompletionGatewayError(provider, operation, message, cause)`

Legacy list-of-dicts context payloads are still accepted through
`normalise_completion_request(...)`.

## Provider Gateways

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

Supports normalized inference fields plus optional vendor params:

- `frequency_penalty`
- `presence_penalty`
- `response_format`
- `seed`
- `tool_choice`
- `tools`
- `user`

### SambaNova

Module: `mugen.core.gateway.completion.sambanova`

Supports normalized inference fields plus optional vendor params:

- `stream`
- `include_usage`
- `frequency_penalty`
- `presence_penalty`
- `response_format`
- `seed`
- `tool_choice`
- `tools`
- `user`

## Configuration Example

```toml
[mugen.modules.core]
gateway.completion = "mugen.core.gateway.completion.bedrock"

[aws.bedrock]
api.region = "us-east-1"
api.access_key_id = "<aws-access-key-id>"
api.secret_access_key = "<aws-secret-access-key>"
api.completion.model = "amazon.nova-lite-v1:0"
api.completion.max_tokens = 1024
api.completion.temp = 0.2
api.completion.top_p = 0.9
```

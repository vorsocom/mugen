"""Shared Anthropic Claude Messages serialization helpers."""

from __future__ import annotations

import json
from typing import Any

from mugen.core.contract.gateway.completion import (
    CompletionContinuationState,
    CompletionGatewayError,
    CompletionReasoningConfig,
    CompletionRequest,
    CompletionResponse,
    CompletionTool,
    CompletionToolCall,
    CompletionToolResult,
    CompletionUsage,
)
from mugen.core.gateway.completion.message_serialization import (
    serialize_completion_message_content,
)
from mugen.core.gateway.completion.sampling_controls import (
    resolve_sampling_parameter_kwargs,
)


def request_uses_claude_workflow_fields(request: CompletionRequest) -> bool:
    """Return whether the request requires Claude content-block workflow support."""
    reasoning = request.reasoning
    if reasoning is not None and reasoning.is_configured():
        return True
    return bool(request.tools or request.tool_results or request.continuation_state)


def operation_config_uses_reasoning(operation_config: dict[str, Any]) -> bool:
    """Return whether operation defaults request Claude reasoning."""
    reasoning_payload = operation_config.get("reasoning")
    if not isinstance(reasoning_payload, dict):
        return False
    reasoning = CompletionReasoningConfig.from_dict(reasoning_payload)
    return reasoning.mode != "disabled" and reasoning.is_configured()


def build_claude_messages_body(
    *,
    request: CompletionRequest,
    operation_config: dict[str, Any],
    model: str,
    provider: str,
    provider_label: str,
    timeout_applied: float | None,
    anthropic_version: str | None = None,
) -> dict[str, Any]:
    """Build an Anthropic Messages body for direct or Bedrock-hosted Claude."""
    body: dict[str, Any] = {"model": model}
    if anthropic_version is not None:
        body = {"anthropic_version": anthropic_version}

    system_text, messages = serialize_claude_messages(request)
    if system_text:
        body["system"] = system_text
    body["messages"] = messages

    max_tokens = request.inference.max_completion_tokens
    if max_tokens is None and "max_completion_tokens" in operation_config:
        max_tokens = int(operation_config["max_completion_tokens"])
    if max_tokens is not None:
        body["max_tokens"] = int(max_tokens)

    body.update(
        resolve_sampling_parameter_kwargs(
            request=request,
            operation_config=operation_config,
            provider=provider,
            provider_label=provider_label,
            timeout_applied=timeout_applied,
        )
    )
    if request.inference.stop:
        body["stop_sequences"] = list(request.inference.stop)

    tools = serialize_claude_tools(request.tools)
    if tools:
        body["tools"] = tools

    reasoning_fields = serialize_claude_reasoning_fields(
        request=request,
        operation_config=operation_config,
        model=model,
        provider=provider,
        provider_label=provider_label,
        timeout_applied=timeout_applied,
    )
    body.update(reasoning_fields)
    return body


def serialize_claude_messages(
    request: CompletionRequest,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Serialize normalized messages plus continuation/tool-result blocks."""
    system_parts: list[str] = []
    messages: list[dict[str, Any]] = []
    for message in request.messages:
        if message.role == "system":
            text = serialize_completion_message_content(message.content)
            if text:
                system_parts.append(text)
            continue

        role = message.role if message.role in {"user", "assistant"} else "user"
        blocks = _content_to_blocks(message.content)
        if role == "user" and message.role not in {"user", "assistant"}:
            blocks = _prefix_first_text_block(blocks, f"[{message.role}] ")
        if blocks:
            messages.append({"role": role, "content": blocks})

    continuation_blocks = _continuation_assistant_blocks(request.continuation_state)
    if continuation_blocks:
        messages.append({"role": "assistant", "content": continuation_blocks})

    tool_result_blocks = [
        serialize_claude_tool_result(result) for result in request.tool_results
    ]
    if tool_result_blocks:
        messages.append({"role": "user", "content": tool_result_blocks})

    system_text = "\n\n".join(system_parts) if system_parts else None
    return system_text, messages


def serialize_claude_tools(tools: list[CompletionTool]) -> list[dict[str, Any]]:
    """Serialize normalized tools to Claude Messages tool definitions."""
    serialized: list[dict[str, Any]] = []
    for tool in tools:
        payload: dict[str, Any] = {
            "name": tool.name,
            "input_schema": dict(tool.input_schema),
        }
        if tool.description is not None:
            payload["description"] = tool.description

        for hint_key in ("anthropic", "bedrock_anthropic"):
            provider_hints = tool.provider_hints.get(hint_key)
            if isinstance(provider_hints, dict):
                payload.update(provider_hints)
        serialized.append(payload)
    return serialized


def serialize_claude_tool_result(result: CompletionToolResult) -> dict[str, Any]:
    """Serialize a normalized tool result as a Claude tool_result block."""
    payload: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": result.tool_call_id,
        "content": _tool_result_content(result.content),
    }
    if result.is_error:
        payload["is_error"] = True
    return payload


def serialize_claude_reasoning_fields(
    *,
    request: CompletionRequest,
    operation_config: dict[str, Any],
    model: str,
    provider: str,
    provider_label: str,
    timeout_applied: float | None,
) -> dict[str, Any]:
    """Serialize provider-neutral reasoning controls to Claude Messages fields."""
    reasoning = _resolve_reasoning_config(request, operation_config)
    if reasoning is None or not reasoning.is_configured():
        return {}

    mode = (reasoning.mode or "").strip().lower().replace("-", "_")
    if mode == "disabled":
        if _is_always_on_thinking_model(model):
            raise CompletionGatewayError(
                provider=provider,
                operation=request.operation,
                message=(
                    f"{provider_label}: Claude model '{model}' does not support "
                    "disabled thinking."
                ),
                timeout_applied=timeout_applied,
            )
        return {}

    if mode in {"", "enabled"}:
        if _is_manual_thinking_unsupported_model(model):
            raise CompletionGatewayError(
                provider=provider,
                operation=request.operation,
                message=(
                    f"{provider_label}: Claude model '{model}' does not support "
                    "manual thinking; use reasoning.mode='adaptive'."
                ),
                timeout_applied=timeout_applied,
            )
        thinking: dict[str, Any] = {"type": "enabled"}
        if reasoning.budget_tokens is not None:
            thinking["budget_tokens"] = int(reasoning.budget_tokens)
        _apply_thinking_display(thinking, reasoning)
        return {"thinking": thinking}

    if mode == "adaptive":
        if not _supports_adaptive_thinking(model):
            raise CompletionGatewayError(
                provider=provider,
                operation=request.operation,
                message=(
                    f"{provider_label}: Claude model '{model}' does not support "
                    "adaptive thinking; use reasoning.mode='enabled' with "
                    "budget_tokens."
                ),
                timeout_applied=timeout_applied,
            )
        thinking = {"type": "adaptive"}
        _apply_thinking_display(thinking, reasoning)
        fields: dict[str, Any] = {"thinking": thinking}
        if reasoning.effort is not None:
            fields["output_config"] = {"effort": reasoning.effort}
        return fields

    raise CompletionGatewayError(
        provider=provider,
        operation=request.operation,
        message=(
            f"{provider_label}: Unsupported reasoning.mode '{reasoning.mode}'. "
            "Expected 'adaptive', 'enabled', or 'disabled'."
        ),
        timeout_applied=timeout_applied,
    )


def parse_claude_messages_response(
    *,
    payload: dict[str, Any],
    model: str,
    provider: str,
    raw: Any,
) -> CompletionResponse:
    """Parse Anthropic Messages response payload to normalized response data."""
    content_blocks = _list_of_dicts(payload.get("content"))
    text = "".join(
        block.get("text", "")
        for block in content_blocks
        if block.get("type") in {None, "text"} and isinstance(block.get("text"), str)
    )

    thinking_blocks = [
        dict(block) for block in content_blocks if block.get("type") == "thinking"
    ]
    redacted_blocks = [
        dict(block)
        for block in content_blocks
        if block.get("type") == "redacted_thinking"
    ]
    output_items = [
        dict(block)
        for block in content_blocks
        if block.get("type") not in {"thinking", "redacted_thinking"}
    ]
    tool_calls = [
        CompletionToolCall(
            id=_optional_string(block.get("id")),
            name=str(block.get("name", "")).strip(),
            arguments=dict(block.get("input") or {}),
            provider_item=dict(block),
        )
        for block in output_items
        if block.get("type") == "tool_use" and isinstance(block.get("name"), str)
    ]

    provider_state = {
        key: payload[key]
        for key in ("id", "type", "role", "model", "stop_reason", "stop_sequence")
        if key in payload
    }
    usage = _usage_from_payload(payload.get("usage"))
    reasoning_state = CompletionContinuationState(
        provider=provider,
        response_id=_optional_string(payload.get("id")),
        output_items=output_items,
        thinking_blocks=thinking_blocks,
        redacted_thinking_blocks=redacted_blocks,
        provider_state=dict(provider_state),
    )

    return CompletionResponse(
        content=text.strip(),
        model=_optional_string(payload.get("model")) or model,
        stop_reason=_optional_string(payload.get("stop_reason")),
        message={
            "role": payload.get("role", "assistant"),
            "content": output_items,
        },
        tool_calls=tool_calls,
        output_items=output_items,
        reasoning_state=reasoning_state,
        provider_state=provider_state,
        usage=usage,
        raw=raw,
    )


def _resolve_reasoning_config(
    request: CompletionRequest,
    operation_config: dict[str, Any],
) -> CompletionReasoningConfig | None:
    reasoning = request.reasoning
    if reasoning is None and isinstance(operation_config.get("reasoning"), dict):
        reasoning = CompletionReasoningConfig.from_dict(operation_config["reasoning"])
    return reasoning


def _apply_thinking_display(
    thinking: dict[str, Any],
    reasoning: CompletionReasoningConfig,
) -> None:
    visibility = reasoning.visibility.strip().lower().replace("-", "_")
    if visibility == "opaque":
        thinking["display"] = "omitted"
    elif visibility in {"summarized", "omitted"}:
        thinking["display"] = visibility


def _content_to_blocks(content: Any) -> list[dict[str, Any]]:
    if content is None:
        return []
    if isinstance(content, list):
        return [dict(item) for item in content if isinstance(item, dict)]
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, dict):
        if isinstance(content.get("type"), str):
            return [dict(content)]
        return [
            {
                "type": "text",
                "text": json.dumps(content, ensure_ascii=True, sort_keys=True),
            }
        ]
    return [{"type": "text", "text": str(content)}]


def _prefix_first_text_block(
    blocks: list[dict[str, Any]],
    prefix: str,
) -> list[dict[str, Any]]:
    if not blocks:
        return [{"type": "text", "text": prefix.rstrip()}]
    prefixed = [dict(block) for block in blocks]
    first = prefixed[0]
    if first.get("type") == "text" and isinstance(first.get("text"), str):
        first["text"] = f"{prefix}{first['text']}"
    else:
        prefixed.insert(0, {"type": "text", "text": prefix.rstrip()})
    return prefixed


def _continuation_assistant_blocks(
    state: CompletionContinuationState | None,
) -> list[dict[str, Any]]:
    if state is None:
        return []
    blocks: list[dict[str, Any]] = []
    blocks.extend(dict(block) for block in state.thinking_blocks)
    blocks.extend(dict(block) for block in state.redacted_thinking_blocks)
    blocks.extend(dict(block) for block in state.output_items)
    return blocks


def _tool_result_content(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, list) and all(isinstance(item, dict) for item in content):
        return [dict(item) for item in content]
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=True, sort_keys=True)


def _usage_from_payload(usage_data: Any) -> CompletionUsage | None:
    if not isinstance(usage_data, dict):
        return None
    input_tokens = usage_data.get("input_tokens")
    output_tokens = usage_data.get("output_tokens")
    if input_tokens is None and output_tokens is None:
        return None
    vendor_fields = {
        key: value
        for key, value in usage_data.items()
        if key not in {"input_tokens", "output_tokens"}
    }
    total_tokens = None
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        total_tokens = input_tokens + output_tokens
    reasoning_tokens = usage_data.get("reasoning_tokens")
    return CompletionUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        reasoning_tokens=reasoning_tokens,
        vendor_fields=vendor_fields,
    )


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalized_model(model: str) -> str:
    return model.strip().lower().replace("_", "-")


def _is_always_on_thinking_model(model: str) -> bool:
    normalized = _normalized_model(model)
    return any(
        marker in normalized
        for marker in ("claude-fable-5", "claude-mythos-5", "claude-mythos-preview")
    )


def _is_manual_thinking_unsupported_model(model: str) -> bool:
    normalized = _normalized_model(model)
    return any(
        marker in normalized
        for marker in (
            "claude-fable-5",
            "claude-mythos-5",
            "claude-opus-4-8",
            "claude-opus-4-7",
        )
    )


def _supports_adaptive_thinking(model: str) -> bool:
    normalized = _normalized_model(model)
    return any(
        marker in normalized
        for marker in (
            "claude-fable-5",
            "claude-mythos-5",
            "claude-mythos-preview",
            "claude-opus-4-8",
            "claude-opus-4-7",
            "claude-opus-4-6",
            "claude-sonnet-4-6",
        )
    )

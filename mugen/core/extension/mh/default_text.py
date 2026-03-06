"""Built-in text message handler powered by the context engine."""

from __future__ import annotations

__all__ = ["DefaultTextMHExtension"]

import asyncio
import json
from types import SimpleNamespace
from typing import Any

from mugen.core.contract.context import ContextScope, ContextTurnRequest, IContextEngine
from mugen.core.contract.context.result import TurnOutcome
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.gateway.completion import (
    CompletionGatewayError,
    CompletionResponse,
    ICompletionGateway,
)
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.utility.context_runtime import scope_key


class DefaultTextMHExtension(IMHExtension):
    """Built-in text message orchestration over the normalized context runtime."""

    _default_extension_timeout_seconds: float = 10.0
    _default_ct_trigger_prefilter_enabled: bool = True
    _completion_error_message: str = "Error: failed to generate response."

    _room_locks: dict[str, asyncio.Lock] = {}

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        completion_gateway: ICompletionGateway,
        config: SimpleNamespace,
        context_engine_service: IContextEngine,
        logging_gateway: ILoggingGateway,
        messaging_service: IMessagingService,
    ) -> None:
        self._completion_gateway = completion_gateway
        self._config = config
        self._context_engine_service = context_engine_service
        self._logging_gateway = logging_gateway
        self._messaging_service = messaging_service
        self._extension_timeout_seconds = self._resolve_extension_timeout_seconds()
        self._ct_trigger_prefilter_enabled = self._resolve_ct_trigger_prefilter_enabled()

    @property
    def message_types(self) -> list[str]:
        return ["text"]

    @property
    def platforms(self) -> list[str]:
        return []

    async def handle_message(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict | str,
        message_context: list[dict] | None = None,
        attachment_context: list[dict] | None = None,
        ingress_metadata: dict[str, Any] | None = None,
        message_id: str | None = None,
        trace_id: str | None = None,
        *,
        scope: ContextScope,
    ) -> list[dict] | None:
        if not isinstance(scope, ContextScope):
            raise TypeError("DefaultTextMHExtension requires ContextScope.")

        command_responses = await self._run_command_extensions(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message=message,
            scope=scope,
        )
        if command_responses:
            return command_responses

        turn_request = ContextTurnRequest(
            scope=scope,
            message_id=message_id,
            trace_id=trace_id,
            user_message=message,
            message_context=list(message_context or []),
            attachment_context=list(attachment_context or []),
            ingress_metadata=dict(ingress_metadata or {}),
        )

        lock = self._get_room_lock(scope)
        async with lock:
            prepared = await self._context_engine_service.prepare_turn(turn_request)
            completion, assistant_response = await self._complete(prepared)
            assistant_response = await self._preprocess_assistant_response(
                platform=platform,
                room_id=room_id,
                sender=sender,
                assistant_response=assistant_response,
                scope=scope,
            )
            if completion is not None and assistant_response.strip() == "":
                self._logging_gateway.warning(
                    "DefaultTextMHExtension.handle_message: "
                    "Assistant response is blank; this may surface as "
                    "'No response generated.' "
                    f"(platform={platform} room_id={room_id} sender={sender}). "
                    "Completion gateway response payload: "
                    f"{self._format_completion_response_for_log(completion)}"
                )

            final_user_responses = [{"type": "text", "content": assistant_response}]
            await self._dispatch_conversational_triggers(
                platform=platform,
                room_id=room_id,
                sender=sender,
                assistant_response=assistant_response,
                scope=scope,
            )
            outcome = self._determine_outcome(
                completion=completion,
                assistant_response=assistant_response,
            )
            await self._commit_turn(
                request=turn_request,
                prepared=prepared,
                completion=completion,
                final_user_responses=final_user_responses,
                outcome=outcome,
            )
            return final_user_responses

    async def _run_command_extensions(
        self,
        *,
        platform: str,
        room_id: str,
        sender: str,
        message: dict | str,
        scope: ContextScope,
    ) -> list[dict]:
        if not isinstance(message, str):
            return []
        user_message = message.strip()
        if user_message == "":
            return []

        responses: list[dict] = []
        for cp_ext in self._messaging_service.cp_extensions:
            if not cp_ext.platform_supported(platform):
                continue
            commands = getattr(cp_ext, "commands", None)
            if not isinstance(commands, list) or user_message not in commands:
                continue
            command_response = await self._await_extension_call(
                stage="cp.process_message",
                ext=cp_ext,
                awaitable=cp_ext.process_message(
                    message,
                    room_id,
                    sender,
                    scope=scope,
                ),
            )
            responses += self._normalize_response_payload_list(
                payload=command_response,
                stage="cp.process_message",
                ext=cp_ext,
            )
        return responses

    async def _complete(
        self,
        prepared,
    ) -> tuple[CompletionResponse | None, str]:
        try:
            completion = await self._completion_gateway.get_completion(
                prepared.completion_request
            )
        except CompletionGatewayError as exc:
            self._logging_gateway.warning(
                "DefaultTextMHExtension.handle_message: "
                f"Completion gateway error ({exc.provider}:{exc.operation}): {exc}"
            )
            return None, self._completion_error_message
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "DefaultTextMHExtension.handle_message: "
                f"Unexpected completion gateway failure: {exc}"
            )
            return None, self._completion_error_message
        return completion, self._coerce_to_text(getattr(completion, "content", None))

    async def _preprocess_assistant_response(
        self,
        *,
        platform: str,
        room_id: str,
        sender: str,
        assistant_response: str,
        scope: ContextScope,
    ) -> str:
        processed_response = assistant_response
        for rpp_ext in self._messaging_service.rpp_extensions:
            if not rpp_ext.platform_supported(platform):
                continue
            preprocessed_response = await self._await_extension_call(
                stage="rpp.preprocess_response",
                ext=rpp_ext,
                awaitable=rpp_ext.preprocess_response(
                    room_id=room_id,
                    user_id=sender,
                    assistant_response=processed_response,
                    scope=scope,
                ),
            )
            if preprocessed_response is not None:
                processed_response = self._coerce_to_text(preprocessed_response)
        return processed_response

    async def _dispatch_conversational_triggers(
        self,
        *,
        platform: str,
        room_id: str,
        sender: str,
        assistant_response: str,
        scope: ContextScope,
    ) -> None:
        for ct_ext in self._messaging_service.ct_extensions:
            if not ct_ext.platform_supported(platform):
                continue
            if not self._ct_extension_triggered(ct_ext, assistant_response):
                continue
            await self._await_extension_call(
                stage="ct.process_message",
                ext=ct_ext,
                awaitable=ct_ext.process_message(
                    message=assistant_response,
                    role="assistant",
                    room_id=room_id,
                    user_id=sender,
                    scope=scope,
                ),
            )

    def _ct_extension_triggered(self, ct_ext: Any, assistant_response: str) -> bool:
        if not self._ct_trigger_prefilter_enabled:
            return True
        triggers = getattr(ct_ext, "triggers", None)
        if not isinstance(triggers, list) or not triggers:
            return True
        response_lc = assistant_response.casefold()
        for trigger in triggers:
            if not isinstance(trigger, str) or trigger == "":
                continue
            if trigger.casefold() in response_lc:
                return True
        return False

    async def _commit_turn(
        self,
        *,
        request: ContextTurnRequest,
        prepared,
        completion: CompletionResponse | None,
        final_user_responses: list[dict[str, Any]],
        outcome: TurnOutcome,
    ) -> None:
        try:
            await self._context_engine_service.commit_turn(
                request=request,
                prepared=prepared,
                completion=completion,
                final_user_responses=final_user_responses,
                outcome=outcome,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "DefaultTextMHExtension.handle_message: "
                f"Context commit failed: {type(exc).__name__}: {exc}"
            )

    @staticmethod
    def _determine_outcome(
        *,
        completion: CompletionResponse | None,
        assistant_response: str,
    ) -> TurnOutcome:
        if completion is None:
            return TurnOutcome.COMPLETION_FAILED
        if assistant_response.strip() == "":
            return TurnOutcome.NO_RESPONSE
        return TurnOutcome.COMPLETED

    def _get_room_lock(self, scope: ContextScope) -> asyncio.Lock:
        lock_key = scope_key(scope)
        lock = self._room_locks.get(lock_key)
        if lock is None:
            lock = asyncio.Lock()
            self._room_locks[lock_key] = lock
        return lock

    async def _await_extension_call(
        self,
        *,
        stage: str,
        ext: Any,
        awaitable: Any,
    ) -> Any | None:
        timeout_seconds = self._extension_timeout_seconds
        try:
            if timeout_seconds is None:
                return await awaitable
            return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            self._logging_gateway.warning(
                "DefaultTextMHExtension.handle_message: "
                f"Extension timeout in {stage} for {type(ext).__name__}."
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "DefaultTextMHExtension.handle_message: "
                f"Extension failure in {stage} for {type(ext).__name__}: {exc}"
            )
        return None

    def _normalize_response_payload_list(
        self,
        *,
        payload: Any,
        stage: str,
        ext: Any | None = None,
    ) -> list[dict]:
        if payload is None:
            return []
        if not isinstance(payload, list):
            self._log_invalid_payload(stage, ext, "response payload list", payload)
            return []
        normalized: list[dict] = []
        for item in payload:
            if isinstance(item, dict):
                normalized.append(item)
                continue
            self._log_invalid_payload(stage, ext, "response payload item", item)
        return normalized

    def _log_invalid_payload(
        self,
        stage: str,
        ext: Any | None,
        expected: str,
        payload: Any,
    ) -> None:
        ext_name = "unknown" if ext is None else type(ext).__name__
        self._logging_gateway.warning(
            "DefaultTextMHExtension.handle_message: "
            f"Invalid {expected} in {stage} for {ext_name} "
            f"(payload_type={type(payload).__name__})."
        )

    @staticmethod
    def _coerce_to_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            try:
                return json.dumps(value, ensure_ascii=True)
            except (TypeError, ValueError):
                return str(value)
        if value is None:
            return ""
        return str(value)

    def _format_completion_response_for_log(self, response: Any) -> str:
        if response is None:
            return "null"
        payload = response
        model_dump = getattr(response, "model_dump", None)
        to_dict = getattr(response, "to_dict", None)
        if callable(model_dump):
            try:
                payload = model_dump()
            except Exception:  # pylint: disable=broad-exception-caught
                payload = response
        elif callable(to_dict):
            try:
                payload = to_dict()
            except Exception:  # pylint: disable=broad-exception-caught
                payload = response
        elif hasattr(response, "__dict__"):
            try:
                payload = vars(response)
            except TypeError:
                payload = response
        try:
            return json.dumps(payload, ensure_ascii=True, default=str)
        except (TypeError, ValueError):
            return str(payload)

    def _messaging_config(self) -> SimpleNamespace:
        return getattr(
            getattr(self._config, "mugen", SimpleNamespace()),
            "messaging",
            SimpleNamespace(),
        )

    def _resolve_extension_timeout_seconds(self) -> float | None:
        messaging_config = self._messaging_config()
        configured_value = getattr(
            messaging_config,
            "extension_timeout_seconds",
            self._default_extension_timeout_seconds,
        )
        if isinstance(configured_value, (int, float)) and not isinstance(
            configured_value,
            bool,
        ):
            if configured_value > 0:
                return float(configured_value)
        return self._default_extension_timeout_seconds

    def _resolve_ct_trigger_prefilter_enabled(self) -> bool:
        messaging_config = self._messaging_config()
        configured_value = getattr(
            messaging_config,
            "ct_trigger_prefilter_enabled",
            self._default_ct_trigger_prefilter_enabled,
        )
        if isinstance(configured_value, bool):
            return configured_value
        return self._default_ct_trigger_prefilter_enabled

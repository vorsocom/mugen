"""Unit tests for mugen.core.extension.mh.default_text."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.contract.context import (
    ContextArtifact,
    ContextBundle,
    ContextCandidate,
    ContextPolicy,
    ContextProvenance,
    ContextScope,
    ContextState,
    ContextTurnRequest,
    PreparedContextTurn,
)
from mugen.core.contract.context.result import TurnOutcome
from mugen.core.contract.gateway.completion import (
    CompletionGatewayError,
    CompletionMessage,
    CompletionRequest,
    CompletionResponse,
)
from mugen.core.extension.mh.default_text import DefaultTextMHExtension


class _BaseExt:
    def __init__(self, supported: bool) -> None:
        self._supported = supported

    def platform_supported(self, _platform: str) -> bool:
        return self._supported


class _CommandExt(_BaseExt):
    def __init__(self, supported: bool, commands, response=None, side_effect=None) -> None:
        super().__init__(supported)
        self.commands = commands
        self.process_message = AsyncMock(return_value=response, side_effect=side_effect)


class _RppExt(_BaseExt):
    def __init__(self, supported: bool, response: object = None, side_effect=None) -> None:
        super().__init__(supported)
        self.preprocess_response = AsyncMock(
            return_value=response,
            side_effect=side_effect,
        )


class _CtExt(_BaseExt):
    def __init__(self, supported: bool, triggers=None, side_effect=None) -> None:
        super().__init__(supported)
        self.triggers = [] if triggers is None else triggers
        self.process_message = AsyncMock(return_value=None, side_effect=side_effect)


def _scope(
    *,
    tenant_id: str = "tenant-1",
    room_id: str = "room-1",
    sender_id: str = "user-1",
) -> ContextScope:
    return ContextScope(
        tenant_id=tenant_id,
        platform="matrix",
        channel_id="matrix",
        room_id=room_id,
        sender_id=sender_id,
        conversation_id=room_id,
    )


def _prepared_turn() -> PreparedContextTurn:
    candidate = ContextCandidate(
        artifact=ContextArtifact(
            artifact_id="persona-1",
            lane="system_persona_policy",
            kind="policy",
            content={"instruction": "Be concise."},
            provenance=ContextProvenance(
                contributor="persona",
                source_kind="config",
                tenant_id="tenant-1",
            ),
        ),
        contributor="persona",
        priority=100,
        score=1.0,
    )
    bundle = ContextBundle(
        policy=ContextPolicy(),
        state=ContextState(revision=3, summary="summary"),
        selected_candidates=(candidate,),
        dropped_candidates=(),
        prefix_fingerprint="prefix-123",
        cache_hints={"prefix_fingerprint": "prefix-123"},
        trace={"selected": [{"artifact_id": "persona-1"}]},
    )
    return PreparedContextTurn(
        completion_request=CompletionRequest(
            messages=[
                CompletionMessage(role="system", content={"lane": "persona"}),
                CompletionMessage(role="user", content="hello"),
            ]
        ),
        bundle=bundle,
        state_handle="tenant-1:matrix:room-1:user-1",
        commit_token="commit-123",
        trace={"selected": [{"artifact_id": "persona-1"}]},
    )


def _make_config(
    *,
    extension_timeout_seconds: float = 10.0,
    ct_trigger_prefilter_enabled: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        mugen=SimpleNamespace(
            messaging=SimpleNamespace(
                extension_timeout_seconds=extension_timeout_seconds,
                ct_trigger_prefilter_enabled=ct_trigger_prefilter_enabled,
            )
        )
    )


def _make_messaging_service(
    *,
    cp_extensions=None,
    rpp_extensions=None,
    ct_extensions=None,
):
    return SimpleNamespace(
        cp_extensions=cp_extensions or [],
        rpp_extensions=rpp_extensions or [],
        ct_extensions=ct_extensions or [],
    )


class TestMugenMessageHandlerTextExtension(unittest.IsolatedAsyncioTestCase):
    """Covers the built-in text orchestration over the context engine."""

    def _new_ext(
        self,
        *,
        completion_result: CompletionResponse | None = None,
        completion_side_effect: object = None,
        prepared: PreparedContextTurn | None = None,
        commit_side_effect: object = None,
        messaging_service=None,
        extension_timeout_seconds: float = 10.0,
        ct_trigger_prefilter_enabled: bool = True,
    ) -> tuple[DefaultTextMHExtension, Mock, Mock]:
        completion_gateway = Mock()
        if completion_side_effect is None:
            completion_gateway.get_completion = AsyncMock(
                return_value=completion_result
                or CompletionResponse(content="assistant answer")
            )
        else:
            completion_gateway.get_completion = AsyncMock(side_effect=completion_side_effect)

        context_engine_service = Mock()
        context_engine_service.prepare_turn = AsyncMock(
            return_value=prepared or _prepared_turn()
        )
        context_engine_service.commit_turn = AsyncMock(side_effect=commit_side_effect)

        ext = DefaultTextMHExtension(
            completion_gateway=completion_gateway,
            config=_make_config(
                extension_timeout_seconds=extension_timeout_seconds,
                ct_trigger_prefilter_enabled=ct_trigger_prefilter_enabled,
            ),
            context_engine_service=context_engine_service,
            logging_gateway=Mock(),
            messaging_service=messaging_service or _make_messaging_service(),
        )
        return ext, completion_gateway, context_engine_service

    async def test_message_type_and_platform_metadata(self) -> None:
        ext, _, _ = self._new_ext()
        self.assertEqual(ext.message_types, ["text"])
        self.assertEqual(ext.platforms, [])

    async def test_command_path_fail_open_and_early_return(self) -> None:
        failing_cp = _CommandExt(
            supported=True,
            commands=["/clear"],
            side_effect=RuntimeError("boom"),
        )
        successful_cp = _CommandExt(
            supported=True,
            commands=["/clear"],
            response=[{"type": "text", "content": "Context cleared."}],
        )
        ext, completion_gateway, context_engine_service = self._new_ext(
            messaging_service=_make_messaging_service(
                cp_extensions=[failing_cp, successful_cp],
            )
        )

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-1",
            sender="user-1",
            message="/clear",
            scope=_scope(),
        )

        self.assertEqual(response, [{"type": "text", "content": "Context cleared."}])
        completion_gateway.get_completion.assert_not_awaited()
        context_engine_service.prepare_turn.assert_not_awaited()
        ext._logging_gateway.warning.assert_called()  # pylint: disable=protected-access
        self.assertEqual(
            successful_cp.process_message.await_args.kwargs["scope"],
            _scope(),
        )

    async def test_handle_message_runs_context_engine_completion_rpp_ct_and_commit(self) -> None:
        rpp = _RppExt(supported=True, response="revised answer")
        ct = _CtExt(supported=True, triggers=["revised"])
        ext, completion_gateway, context_engine_service = self._new_ext(
            completion_result=CompletionResponse(content="assistant answer"),
            messaging_service=_make_messaging_service(
                rpp_extensions=[rpp],
                ct_extensions=[ct],
            ),
        )
        scope = _scope()

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-1",
            sender="user-1",
            message="hello",
            message_context=[{"type": "seed", "content": "ctx"}],
            attachment_context=[{"type": "attachment", "content": {"id": "a1"}}],
            ingress_metadata={"trace": "123"},
            message_id="msg-1",
            trace_id="trace-1",
            scope=scope,
        )

        self.assertEqual(response, [{"type": "text", "content": "revised answer"}])
        prepare_request = context_engine_service.prepare_turn.await_args.args[0]
        self.assertEqual(
            prepare_request,
            ContextTurnRequest(
                scope=scope,
                message_id="msg-1",
                trace_id="trace-1",
                user_message="hello",
                message_context=[{"type": "seed", "content": "ctx"}],
                attachment_context=[{"type": "attachment", "content": {"id": "a1"}}],
                ingress_metadata={"trace": "123"},
            ),
        )
        completion_gateway.get_completion.assert_awaited_once()
        self.assertEqual(
            completion_gateway.get_completion.await_args.args[0].messages[-1].content,
            "hello",
        )
        rpp.preprocess_response.assert_awaited_once()
        self.assertEqual(rpp.preprocess_response.await_args.kwargs["scope"], scope)
        ct.process_message.assert_awaited_once()
        self.assertEqual(ct.process_message.await_args.kwargs["scope"], scope)
        commit_call = context_engine_service.commit_turn.await_args.kwargs
        self.assertEqual(commit_call["final_user_responses"], response)
        self.assertEqual(commit_call["outcome"], TurnOutcome.COMPLETED)

    async def test_completion_failure_returns_error_and_commits_failed_outcome(self) -> None:
        ext, _, context_engine_service = self._new_ext(
            completion_side_effect=CompletionGatewayError(
                provider="bedrock",
                operation="completion",
                message="failed",
            ),
        )

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-1",
            sender="user-1",
            message="hello",
            scope=_scope(),
        )

        self.assertEqual(
            response,
            [{"type": "text", "content": ext._completion_error_message}],  # pylint: disable=protected-access
        )
        commit_call = context_engine_service.commit_turn.await_args.kwargs
        self.assertIsNone(commit_call["completion"])
        self.assertEqual(commit_call["outcome"], TurnOutcome.COMPLETION_FAILED)

    async def test_commit_failure_is_fail_open(self) -> None:
        ext, _, context_engine_service = self._new_ext(
            commit_side_effect=RuntimeError("persist boom")
        )

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-1",
            sender="user-1",
            message="hello",
            scope=_scope(),
        )

        self.assertEqual(response, [{"type": "text", "content": "assistant answer"}])
        context_engine_service.commit_turn.assert_awaited_once()
        ext._logging_gateway.warning.assert_called()  # pylint: disable=protected-access

    async def test_completion_content_is_serialized_to_text(self) -> None:
        ext, _, _ = self._new_ext(
            completion_result=CompletionResponse(content={"structured": True})
        )

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-1",
            sender="user-1",
            message="hello",
            scope=_scope(),
        )

        self.assertEqual(
            response,
            [{"type": "text", "content": json.dumps({"structured": True}, ensure_ascii=True)}],
        )

    async def test_blank_assistant_response_logs_completion_payload(self) -> None:
        ext, _, _ = self._new_ext(
            completion_result=CompletionResponse(content="", model="gpt-test")
        )

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-1",
            sender="user-1",
            message="hello",
            scope=_scope(),
        )

        self.assertEqual(response, [{"type": "text", "content": ""}])
        ext._logging_gateway.warning.assert_called()  # pylint: disable=protected-access

    async def test_ct_trigger_prefilter_enabled(self) -> None:
        ct_matching = _CtExt(supported=True, triggers=["urgent"])
        ct_not_matching = _CtExt(supported=True, triggers=["billing"])
        ct_empty = _CtExt(supported=True, triggers=[])
        ext, _, _ = self._new_ext(
            completion_result=CompletionResponse(content="Need URGENT support"),
            messaging_service=_make_messaging_service(
                ct_extensions=[ct_matching, ct_not_matching, ct_empty],
            ),
            ct_trigger_prefilter_enabled=True,
        )

        await ext.handle_message(
            platform="matrix",
            room_id="room-1",
            sender="user-1",
            message="hello",
            scope=_scope(),
        )

        ct_matching.process_message.assert_awaited_once()
        ct_not_matching.process_message.assert_not_awaited()
        ct_empty.process_message.assert_awaited_once()

    async def test_ct_trigger_prefilter_disabled(self) -> None:
        ct_matching = _CtExt(supported=True, triggers=["urgent"])
        ct_not_matching = _CtExt(supported=True, triggers=["billing"])
        ext, _, _ = self._new_ext(
            completion_result=CompletionResponse(content="Need URGENT support"),
            messaging_service=_make_messaging_service(
                ct_extensions=[ct_matching, ct_not_matching],
            ),
            ct_trigger_prefilter_enabled=False,
        )

        await ext.handle_message(
            platform="matrix",
            room_id="room-1",
            sender="user-1",
            message="hello",
            scope=_scope(),
        )

        ct_matching.process_message.assert_awaited_once()
        ct_not_matching.process_message.assert_awaited_once()

    async def test_invalid_command_payload_is_ignored(self) -> None:
        cp = _CommandExt(
            supported=True,
            commands=["/clear"],
            response=["bad-item", {"type": "text", "content": "ok"}],
        )
        ext, _, _ = self._new_ext(
            messaging_service=_make_messaging_service(cp_extensions=[cp])
        )

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-1",
            sender="user-1",
            message="/clear",
            scope=_scope(),
        )

        self.assertEqual(response, [{"type": "text", "content": "ok"}])
        ext._logging_gateway.warning.assert_called()  # pylint: disable=protected-access

    async def test_handle_message_requires_context_scope(self) -> None:
        ext, _, _ = self._new_ext()

        with self.assertRaisesRegex(TypeError, "ContextScope"):
            await ext.handle_message(
                platform="matrix",
                room_id="room-1",
                sender="user-1",
                message="hello",
                scope="bad-scope",
            )

    async def test_room_lock_serializes_same_scope_turns(self) -> None:
        state = {"active": 0, "max_active": 0}

        async def _prepare_turn(_request):
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
            await asyncio.sleep(0.01)
            state["active"] -= 1
            return _prepared_turn()

        ext, _, context_engine_service = self._new_ext()
        context_engine_service.prepare_turn = AsyncMock(side_effect=_prepare_turn)

        await asyncio.gather(
            ext.handle_message(
                platform="matrix",
                room_id="room-1",
                sender="user-1",
                message="one",
                scope=_scope(),
            ),
            ext.handle_message(
                platform="matrix",
                room_id="room-1",
                sender="user-1",
                message="two",
                scope=_scope(),
            ),
        )

        self.assertEqual(state["max_active"], 1)

    async def test_run_command_extensions_skips_non_string_blank_and_unsupported_cases(
        self,
    ) -> None:
        supported = _CommandExt(supported=True, commands=["/clear"], response=[])
        unsupported = _CommandExt(supported=False, commands=["/clear"], response=[])
        invalid_commands = _CommandExt(supported=True, commands="bad", response=[])
        ext, _, _ = self._new_ext(
            messaging_service=_make_messaging_service(
                cp_extensions=[supported, unsupported, invalid_commands]
            )
        )

        self.assertEqual(
            await ext._run_command_extensions(  # pylint: disable=protected-access
                platform="matrix",
                room_id="room-1",
                sender="user-1",
                message={"text": "hello"},
                scope=_scope(),
            ),
            [],
        )
        self.assertEqual(
            await ext._run_command_extensions(  # pylint: disable=protected-access
                platform="matrix",
                room_id="room-1",
                sender="user-1",
                message="   ",
                scope=_scope(),
            ),
            [],
        )
        self.assertEqual(
            await ext._run_command_extensions(  # pylint: disable=protected-access
                platform="matrix",
                room_id="room-1",
                sender="user-1",
                message="/noop",
                scope=_scope(),
            ),
            [],
        )
        supported.process_message.assert_not_awaited()
        unsupported.process_message.assert_not_awaited()
        invalid_commands.process_message.assert_not_awaited()

    async def test_complete_handles_unexpected_gateway_exception(self) -> None:
        ext, _, _ = self._new_ext(completion_side_effect=RuntimeError("boom"))

        completion, assistant_response = await ext._complete(_prepared_turn())  # pylint: disable=protected-access

        self.assertIsNone(completion)
        self.assertEqual(assistant_response, ext._completion_error_message)  # pylint: disable=protected-access
        ext._logging_gateway.warning.assert_called()  # pylint: disable=protected-access

    async def test_preprocess_and_trigger_helpers_cover_skip_paths(self) -> None:
        unsupported_rpp = _RppExt(supported=False, response="skip")
        none_rpp = _RppExt(supported=True, response=None)
        unsupported_ct = _CtExt(supported=False, triggers=["hello"])
        miss_ct = _CtExt(supported=True, triggers=["missing"])
        ext, _, _ = self._new_ext(
            messaging_service=_make_messaging_service(
                rpp_extensions=[unsupported_rpp, none_rpp],
                ct_extensions=[unsupported_ct, miss_ct],
            )
        )

        processed = await ext._preprocess_assistant_response(  # pylint: disable=protected-access
            platform="matrix",
            room_id="room-1",
            sender="user-1",
            assistant_response="hello",
            scope=_scope(),
        )
        await ext._dispatch_conversational_triggers(  # pylint: disable=protected-access
            platform="matrix",
            room_id="room-1",
            sender="user-1",
            assistant_response="hello",
            scope=_scope(),
        )

        self.assertEqual(processed, "hello")
        unsupported_rpp.preprocess_response.assert_not_awaited()
        unsupported_ct.process_message.assert_not_awaited()
        miss_ct.process_message.assert_not_awaited()
        self.assertTrue(
            ext._ct_extension_triggered(  # pylint: disable=protected-access
                _CtExt(supported=True, triggers=[None, "", "hello"]),
                "hello there",
            )
        )

    async def test_await_extension_call_covers_timeout_and_exception_paths(self) -> None:
        ext, _, _ = self._new_ext(extension_timeout_seconds=0.001)

        async def _sleep():
            await asyncio.sleep(0.01)
            return "late"

        async def _fail():
            raise RuntimeError("boom")

        self.assertIsNone(
            await ext._await_extension_call(  # pylint: disable=protected-access
                stage="test.timeout",
                ext=_BaseExt(True),
                awaitable=_sleep(),
            )
        )
        self.assertIsNone(
            await ext._await_extension_call(  # pylint: disable=protected-access
                stage="test.failure",
                ext=_BaseExt(True),
                awaitable=_fail(),
            )
        )
        ext._extension_timeout_seconds = None  # pylint: disable=protected-access
        self.assertEqual(
            await ext._await_extension_call(  # pylint: disable=protected-access
                stage="test.success",
                ext=_BaseExt(True),
                awaitable=asyncio.sleep(0, result="ok"),
            ),
            "ok",
        )
        ext._logging_gateway.warning.assert_called()  # pylint: disable=protected-access

    def test_response_normalization_and_text_coercion_helpers_cover_edge_paths(self) -> None:
        ext, _, _ = self._new_ext()
        circular: list[object] = []
        circular.append(circular)

        self.assertEqual(
            ext._normalize_response_payload_list(payload=None, stage="test"),  # pylint: disable=protected-access
            [],
        )
        self.assertEqual(
            ext._normalize_response_payload_list(payload="bad", stage="test"),  # pylint: disable=protected-access
            [],
        )
        self.assertEqual(
            ext._normalize_response_payload_list(  # pylint: disable=protected-access
                payload=[{"type": "text", "content": "ok"}, "bad"],
                stage="test",
            ),
            [{"type": "text", "content": "ok"}],
        )
        self.assertEqual(ext._coerce_to_text(None), "")  # pylint: disable=protected-access
        self.assertEqual(ext._coerce_to_text(5), "5")  # pylint: disable=protected-access
        self.assertEqual(
            ext._coerce_to_text(circular),  # pylint: disable=protected-access
            str(circular),
        )

    def test_format_completion_response_for_log_and_config_helpers_cover_fallbacks(
        self,
    ) -> None:
        class _ModelDumpResponse:
            def model_dump(self):
                return {"value": 1}

        class _ToDictResponse:
            def to_dict(self):
                return {"value": 2}

        class _VarsResponse:
            def __init__(self) -> None:
                self.value = 3

        class _FallbackResponse:
            __slots__ = ()

            def __str__(self) -> str:
                return "fallback"

        class _CircularDumpResponse:
            def model_dump(self):
                payload = {}
                payload["self"] = payload
                return payload

        class _BrokenModelDumpResponse:
            def model_dump(self):
                raise RuntimeError("boom")

        class _BrokenToDictResponse:
            def to_dict(self):
                raise RuntimeError("boom")

        class _BrokenVarsResponse:
            def __init__(self) -> None:
                self.value = 4

        ext, _, _ = self._new_ext(
            extension_timeout_seconds="bad",  # type: ignore[arg-type]
            ct_trigger_prefilter_enabled="bad",  # type: ignore[arg-type]
        )
        ext_zero, _, _ = self._new_ext(extension_timeout_seconds=0)

        self.assertEqual(
            ext._format_completion_response_for_log(None),  # pylint: disable=protected-access
            "null",
        )
        self.assertEqual(
            ext._format_completion_response_for_log(_ModelDumpResponse()),  # pylint: disable=protected-access
            '{"value": 1}',
        )
        self.assertEqual(
            ext._format_completion_response_for_log(_ToDictResponse()),  # pylint: disable=protected-access
            '{"value": 2}',
        )
        self.assertEqual(
            ext._format_completion_response_for_log(_VarsResponse()),  # pylint: disable=protected-access
            '{"value": 3}',
        )
        self.assertEqual(
            ext._format_completion_response_for_log(_FallbackResponse()),  # pylint: disable=protected-access
            '"fallback"',
        )
        self.assertEqual(
            ext._format_completion_response_for_log(_CircularDumpResponse()),  # pylint: disable=protected-access
            "{'self': {...}}",
        )
        self.assertIn(
            "BrokenModelDumpResponse",
            ext._format_completion_response_for_log(_BrokenModelDumpResponse()),  # pylint: disable=protected-access
        )
        self.assertIn(
            "BrokenToDictResponse",
            ext._format_completion_response_for_log(_BrokenToDictResponse()),  # pylint: disable=protected-access
        )
        with patch("builtins.vars", side_effect=TypeError("boom")):
            self.assertIn(
                "BrokenVarsResponse",
                ext._format_completion_response_for_log(_BrokenVarsResponse()),  # pylint: disable=protected-access
            )
        self.assertEqual(
            ext._extension_timeout_seconds,  # pylint: disable=protected-access
            ext._default_extension_timeout_seconds,  # pylint: disable=protected-access
        )
        self.assertEqual(
            ext_zero._extension_timeout_seconds,  # pylint: disable=protected-access
            ext_zero._default_extension_timeout_seconds,  # pylint: disable=protected-access
        )
        self.assertEqual(
            ext._ct_trigger_prefilter_enabled,  # pylint: disable=protected-access
            ext._default_ct_trigger_prefilter_enabled,  # pylint: disable=protected-access
        )
